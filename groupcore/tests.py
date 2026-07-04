from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from deposits.models import DepositSubmission
from groupcore.models import MemberProfile, SavingsAccount
from groupcore.week_cycle import current_saving_week
from loans.models import LoanRequest


class SavingWeekCycleTests(SimpleTestCase):
    def test_first_configured_year_uses_group_week_one_start(self):
        saving_week = current_saving_week(
            week_one_start=date(2025, 7, 7),
            today=date(2025, 7, 7),
        )

        self.assertEqual(saving_week.week_start, date(2025, 7, 7))
        self.assertEqual(saving_week.week_number, 1)
        self.assertEqual(saving_week.saving_year, 2025)

    def test_week_number_resets_for_next_saving_year(self):
        saving_week = current_saving_week(
            week_one_start=date(2025, 7, 7),
            today=date(2026, 7, 3),
        )

        self.assertEqual(saving_week.cycle_start, date(2026, 1, 5))
        self.assertEqual(saving_week.week_start, date(2026, 6, 29))
        self.assertEqual(saving_week.week_number, 26)
        self.assertEqual(saving_week.saving_year, 2026)

    def test_new_year_waits_for_the_first_matching_saving_weekday(self):
        saving_week = current_saving_week(
            week_one_start=date(2025, 7, 7),
            today=date(2026, 1, 2),
        )

        self.assertEqual(saving_week.cycle_start, date(2026, 1, 5))
        self.assertEqual(saving_week.week_start, date(2026, 1, 5))
        self.assertEqual(saving_week.week_number, 1)


class RootUrlTests(SimpleTestCase):
    def test_root_redirects_to_login(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/login/')


class YearEndSettlementYearFilterTests(TestCase):
    def setUp(self):
        self.current_year = timezone.localdate().year
        self.previous_year = self.current_year - 1
        self.treasurer = MemberProfile.objects.create_user(
            username='treasurer',
            password='pass12345',
            role='TREASURER',
        )
        self.member = MemberProfile.objects.create_user(
            username='member',
            password='pass12345',
            role='MEMBER',
        )
        self._deposit(
            payment_week=date(self.previous_year, 12, 29),
            payment_date=date(self.current_year, 1, 2),
            saving_amount=Decimal('1000.00'),
        )
        self._deposit(
            payment_week=date(self.current_year, 1, 5),
            payment_date=date(self.current_year, 1, 5),
            saving_amount=Decimal('9000.00'),
        )
        self.previous_loan = self._loan(
            principal=Decimal('1000.00'),
            approved_on=timezone.make_aware(datetime(self.previous_year, 6, 1, 9, 0)),
        )
        self._loan(
            principal=Decimal('5000.00'),
            approved_on=timezone.make_aware(datetime(self.current_year, 6, 1, 9, 0)),
        )

    def _deposit(self, payment_week, payment_date, saving_amount):
        return DepositSubmission.objects.create(
            member=self.member,
            submitted_by=self.treasurer,
            payment_week=payment_week,
            starting_week=payment_week,
            weeks_covered=1,
            saving_amount=saving_amount,
            proof='proofs/test.jpg',
            payment_date=payment_date,
            payment_time=time(9, 0),
            status='APPROVED',
        )

    def _loan(self, principal, approved_on):
        return LoanRequest.objects.create(
            member=self.member,
            principal=principal,
            monthly_interest_rate=Decimal('2.00'),
            duration_months=1,
            status=LoanRequest.STATUS_APPROVED,
            approved_on=approved_on,
        )

    def test_year_end_settlement_can_display_previous_year(self):
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(
            reverse('year_end_settlement'),
            {'year': self.previous_year},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['target_year'], self.previous_year)
        self.assertEqual(response.context['group_savings_total'], Decimal('1000'))
        self.assertEqual(response.context['loan_interest_pool'], self.previous_loan.total_interest)
        self.assertContains(
            response,
            f'Viewing the historical settlement calculation for {self.previous_year}.',
        )


class HistoricalDataImportCommandTests(TestCase):
    def setUp(self):
        self.treasurer = MemberProfile.objects.create_user(
            username='treasurer',
            password='pass12345',
            role='TREASURER',
        )

    def _write_import_files(self, directory, expected_total='21000'):
        members_path = Path(directory) / 'members.csv'
        transactions_path = Path(directory) / 'transactions.csv'
        members_path.write_text(
            '\n'.join([
                'username,first_name,last_name,email,phone_number,role,account_labels,is_active',
                'jane_member,Jane,Member,jane@example.com,+256700000001,MEMBER,A1,true',
            ]),
            encoding='utf-8',
        )
        transactions_path.write_text(
            '\n'.join([
                (
                    'transaction_reference,username,account_label,payment_week,payment_date,payment_time,'
                    'saving_amount,welfare_amount,annual_subscription_amount,fine_amount,shares_amount,'
                    'loan_repayment_amount,expected_total,status,remarks,proof_reference'
                ),
                (
                    'OLD-001,jane_member,A1,2026-06-22,2026-06-26,09:30,'
                    f'20000,1000,0,0,0,0,{expected_total},APPROVED,Historical import,proofs/old-001.jpg'
                ),
            ]),
            encoding='utf-8',
        )
        return members_path, transactions_path

    def test_dry_run_validates_without_writing_data(self):
        with TemporaryDirectory() as directory:
            members_path, transactions_path = self._write_import_files(directory)
            report_path = Path(directory) / 'report.csv'

            call_command(
                'import_historical_data',
                members=str(members_path),
                transactions=str(transactions_path),
                submitted_by='treasurer',
                report=str(report_path),
            )

            self.assertFalse(MemberProfile.objects.filter(username='jane_member').exists())
            self.assertIn('VALID_NEW_MEMBER', report_path.read_text(encoding='utf-8'))
            self.assertIn('VALID_NEW_TRANSACTION', report_path.read_text(encoding='utf-8'))

    def test_commit_imports_members_accounts_and_historical_transactions(self):
        with TemporaryDirectory() as directory:
            members_path, transactions_path = self._write_import_files(directory)
            report_path = Path(directory) / 'report.csv'

            call_command(
                'import_historical_data',
                members=str(members_path),
                transactions=str(transactions_path),
                submitted_by='treasurer',
                report=str(report_path),
                commit=True,
            )

            member = MemberProfile.objects.get(username='jane_member')
            account = SavingsAccount.objects.get(owner=member, label='A1')
            deposit = DepositSubmission.objects.get(import_reference='OLD-001')
            self.assertEqual(deposit.member, member)
            self.assertEqual(deposit.account, account)
            self.assertEqual(deposit.payment_week, date(2026, 6, 22))
            self.assertEqual(deposit.payment_date, date(2026, 6, 26))
            self.assertEqual(deposit.payment_time, time(9, 30))
            self.assertEqual(deposit.amount, Decimal('21000.00'))
            self.assertEqual(deposit.status, 'APPROVED')
            self.assertIn('CREATED_TRANSACTION', report_path.read_text(encoding='utf-8'))

    def test_rerun_skips_duplicate_transactions_by_reference(self):
        with TemporaryDirectory() as directory:
            members_path, transactions_path = self._write_import_files(directory)
            report_path = Path(directory) / 'report.csv'
            duplicate_report_path = Path(directory) / 'duplicate-report.csv'

            call_command(
                'import_historical_data',
                members=str(members_path),
                transactions=str(transactions_path),
                submitted_by='treasurer',
                report=str(report_path),
                commit=True,
            )
            call_command(
                'import_historical_data',
                members=str(members_path),
                transactions=str(transactions_path),
                submitted_by='treasurer',
                report=str(duplicate_report_path),
                commit=True,
            )

            self.assertEqual(DepositSubmission.objects.filter(import_reference='OLD-001').count(), 1)
            self.assertIn('SKIPPED_DUPLICATE', duplicate_report_path.read_text(encoding='utf-8'))

    def test_invalid_transaction_report_blocks_import(self):
        with TemporaryDirectory() as directory:
            members_path, transactions_path = self._write_import_files(directory, expected_total='99999')
            report_path = Path(directory) / 'report.csv'

            with self.assertRaises(CommandError):
                call_command(
                    'import_historical_data',
                    members=str(members_path),
                    transactions=str(transactions_path),
                    submitted_by='treasurer',
                    report=str(report_path),
                    commit=True,
                )

            self.assertFalse(MemberProfile.objects.filter(username='jane_member').exists())
            self.assertFalse(DepositSubmission.objects.filter(import_reference='OLD-001').exists())
            report_text = report_path.read_text(encoding='utf-8')
            self.assertIn('ERROR', report_text)
            self.assertIn('does not match amount sum', report_text)
