from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from deposits.models import DepositSubmission
from fines.models import Fine
from groupcore.models import GroupSettings, MemberProfile, SavingsAccount
from groupcore.week_cycle import current_saving_week, first_friday_of_year
from loans.models import LoanRequest


class SavingWeekCycleTests(SimpleTestCase):
    def test_first_configured_year_uses_group_week_one_start(self):
        saving_week = current_saving_week(
            week_one_start=date(2026, 1, 2),
            today=date(2026, 1, 2),
        )

        self.assertEqual(saving_week.week_start, date(2026, 1, 2))
        self.assertEqual(saving_week.week_number, 1)
        self.assertEqual(saving_week.saving_year, 2026)

    def test_week_number_resets_for_next_saving_year(self):
        saving_week = current_saving_week(
            week_one_start=date(2026, 1, 2),
            today=date(2027, 7, 3),
        )

        self.assertEqual(saving_week.cycle_start, date(2027, 1, 1))
        self.assertEqual(saving_week.week_start, date(2027, 7, 2))
        self.assertEqual(saving_week.week_number, 27)
        self.assertEqual(saving_week.saving_year, 2027)

    def test_new_year_waits_for_the_first_friday_saving_week(self):
        saving_week = current_saving_week(
            week_one_start=date(2026, 1, 2),
            today=date(2028, 1, 3),
        )

        self.assertEqual(saving_week.cycle_start, date(2028, 1, 7))
        self.assertEqual(saving_week.week_start, date(2028, 1, 7))
        self.assertEqual(saving_week.week_number, 1)


class RootUrlTests(SimpleTestCase):
    def test_root_redirects_to_login(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/login/')


class GroupSettingsSetupTests(TestCase):
    def setUp(self):
        self.treasurer = MemberProfile.objects.create_user(
            username='treasurer',
            password='pass12345',
            role='TREASURER',
        )
        self.chairman = MemberProfile.objects.create_user(
            username='chairman',
            password='pass12345',
            role='CHAIRMAN',
        )
        self.member = MemberProfile.objects.create_user(
            username='member',
            password='pass12345',
            role='MEMBER',
        )

    def test_group_settings_defaults_to_first_friday_of_current_year(self):
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(reverse('group_settings'))

        expected_start = first_friday_of_year(timezone.localdate().year)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['settings_exists'])
        self.assertEqual(response.context['form'].initial['week_one_start'], expected_start)
        self.assertEqual(response.context['saving_week'].cycle_start, expected_start)

    def test_treasurer_can_create_group_settings(self):
        self.client.login(username='treasurer', password='pass12345')
        week_one_start = first_friday_of_year(timezone.localdate().year)

        response = self.client.post(
            reverse('group_settings'),
            {'week_one_start': week_one_start.isoformat()},
        )

        self.assertRedirects(response, reverse('group_settings'))
        self.assertEqual(GroupSettings.objects.count(), 1)
        self.assertEqual(GroupSettings.get_active().week_one_start, week_one_start)

    def test_chairman_can_update_group_settings(self):
        GroupSettings.objects.create(week_one_start=date(2026, 1, 2))
        self.client.login(username='chairman', password='pass12345')

        response = self.client.post(
            reverse('group_settings'),
            {'week_one_start': '2027-01-01'},
        )

        self.assertRedirects(response, reverse('group_settings'))
        self.assertEqual(GroupSettings.objects.count(), 1)
        self.assertEqual(GroupSettings.get_active().week_one_start, date(2027, 1, 1))

    def test_member_cannot_access_group_settings(self):
        self.client.login(username='member', password='pass12345')

        response = self.client.get(reverse('group_settings'))

        self.assertRedirects(response, reverse('member_dashboard'))

    def test_group_settings_save_reuses_existing_record(self):
        GroupSettings.objects.create(week_one_start=date(2026, 1, 2))
        GroupSettings.objects.create(week_one_start=date(2027, 1, 1))

        self.assertEqual(GroupSettings.objects.count(), 1)
        self.assertEqual(GroupSettings.get_active().week_one_start, date(2027, 1, 1))

    def test_member_deposit_submission_has_friendly_message_when_cycle_missing(self):
        self.client.login(username='member', password='pass12345')

        response = self.client.get(reverse('submit_deposit'))

        self.assertRedirects(response, reverse('member_dashboard'))
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn(
            "The saving cycle has not been opened yet. Please contact the Treasurer.",
            messages,
        )

    def test_chairman_deposit_submission_redirects_to_setup_when_cycle_missing(self):
        self.client.login(username='chairman', password='pass12345')

        response = self.client.get(reverse('submit_deposit'))

        self.assertRedirects(response, reverse('group_settings'))


class LeadershipAccountSelectionTests(TestCase):
    def setUp(self):
        GroupSettings.objects.create(week_one_start=first_friday_of_year(timezone.localdate().year))
        self.secretary = MemberProfile.objects.create_user(
            username='secretary',
            password='pass12345',
            role='SECRETARY',
        )
        SavingsAccount.objects.create(owner=self.secretary, label='A1')
        SavingsAccount.objects.create(owner=self.secretary, label='A2')

    def test_secretary_management_dashboard_does_not_require_account_selection(self):
        self.client.login(username='secretary', password='pass12345')

        response = self.client.get(reverse('secretary_dashboard'))

        self.assertEqual(response.status_code, 200)

    def test_secretary_member_feature_requires_account_selection(self):
        self.client.login(username='secretary', password='pass12345')

        response = self.client.get(reverse('submit_deposit'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('select_savings_account')))
        self.assertIn(reverse('submit_deposit'), response['Location'])

    def test_account_selection_returns_to_requested_member_feature(self):
        self.client.login(username='secretary', password='pass12345')
        account = SavingsAccount.objects.get(owner=self.secretary, label='A2')

        response = self.client.post(
            reverse('select_savings_account'),
            {'account_id': account.id, 'next': reverse('my_contributions')},
        )

        self.assertRedirects(response, reverse('my_contributions'))


class MemberWeekProgressTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.week_one_start = first_friday_of_year(today.year)
        GroupSettings.objects.create(week_one_start=self.week_one_start)
        self.member = MemberProfile.objects.create_user(
            username='member',
            password='pass12345',
            role='MEMBER',
        )
        self.account = SavingsAccount.objects.create(owner=self.member, label='A1')

    def test_member_dashboard_reports_missing_due_weeks(self):
        self.client.login(username='member', password='pass12345')

        response = self.client.get(reverse('member_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['week_progress']['status'], 'Behind')
        self.assertGreater(response.context['week_progress']['missing_weeks_count'], 0)


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
                    'OLD-001,jane_member,A1,2026-06-26,2026-06-26,09:30,'
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
            self.assertEqual(deposit.payment_week, date(2026, 6, 26))
            self.assertEqual(deposit.payment_date, date(2026, 6, 26))
            self.assertEqual(deposit.payment_time, time(9, 30))
            self.assertEqual(deposit.amount, Decimal('21000.00'))
            self.assertEqual(deposit.status, 'APPROVED')
            self.assertIn('CREATED_TRANSACTION', report_path.read_text(encoding='utf-8'))

    def test_commit_import_marks_matching_missed_week_fine_paid(self):
        member = MemberProfile.objects.create_user(
            username='jane_member',
            password='pass12345',
            role='MEMBER',
        )
        account = SavingsAccount.objects.create(owner=member, label='A1')
        fine = Fine.objects.create(
            member=member,
            account=account,
            fine_type='MISSED_WEEKLY_SAVING',
            reference_week=date(2026, 6, 26),
            reason='Failed to save for account A1 for week closing 2026-06-26',
            amount=Decimal('2000.00'),
            issued_by=self.treasurer,
        )

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

        fine.refresh_from_db()
        self.assertTrue(fine.is_paid)

    def test_members_import_accepts_full_account_name_labels(self):
        with TemporaryDirectory() as directory:
            members_path = Path(directory) / 'members.csv'
            report_path = Path(directory) / 'report.csv'
            members_path.write_text(
                '\n'.join([
                    'username,first_name,last_name,email,phone_number,role,account_labels,is_active',
                    'long_label_member,Long,Label,long@example.com,+256700000005,MEMBER,Kolyangha Martin Luther,true',
                ]),
                encoding='utf-8',
            )

            call_command(
                'import_historical_data',
                members=str(members_path),
                report=str(report_path),
                commit=True,
            )

            member = MemberProfile.objects.get(username='long_label_member')
            self.assertTrue(
                SavingsAccount.objects.filter(
                    owner=member,
                    label='Kolyangha Martin Luther',
                ).exists()
            )
            self.assertIn('CREATED_MEMBER', report_path.read_text(encoding='utf-8'))

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


class UsernameUpdateCommandTests(TestCase):
    def test_dry_run_does_not_change_username(self):
        MemberProfile.objects.create_user(
            username='kolyangha_martin_luther',
            email='martin@example.com',
            password='pass12345',
        )
        with TemporaryDirectory() as directory:
            mapping_path = Path(directory) / 'mapping.csv'
            report_path = Path(directory) / 'report.csv'
            mapping_path.write_text(
                '\n'.join([
                    'old_username,new_username,email,name',
                    'kolyangha_martin_luther,KolyanghaM,martin@example.com,Kolyangha Martin Luther',
                ]),
                encoding='utf-8',
            )

            call_command(
                'update_usernames_from_csv',
                file=str(mapping_path),
                report=str(report_path),
            )

            self.assertTrue(MemberProfile.objects.filter(username='kolyangha_martin_luther').exists())
            self.assertFalse(MemberProfile.objects.filter(username='KolyanghaM').exists())
            self.assertIn('VALID_UPDATE', report_path.read_text(encoding='utf-8'))

    def test_commit_updates_username(self):
        MemberProfile.objects.create_user(
            username='kolyangha_martin_luther',
            email='martin@example.com',
            password='pass12345',
        )
        with TemporaryDirectory() as directory:
            mapping_path = Path(directory) / 'mapping.csv'
            report_path = Path(directory) / 'report.csv'
            mapping_path.write_text(
                '\n'.join([
                    'old_username,new_username,email,name',
                    'kolyangha_martin_luther,KolyanghaM,martin@example.com,Kolyangha Martin Luther',
                ]),
                encoding='utf-8',
            )

            call_command(
                'update_usernames_from_csv',
                file=str(mapping_path),
                report=str(report_path),
                commit=True,
            )

            self.assertFalse(MemberProfile.objects.filter(username='kolyangha_martin_luther').exists())
            self.assertTrue(MemberProfile.objects.filter(username='KolyanghaM').exists())
            self.assertIn('UPDATED_USERNAME', report_path.read_text(encoding='utf-8'))

    def test_conflicting_new_username_blocks_updates(self):
        MemberProfile.objects.create_user(
            username='kolyangha_martin_luther',
            email='martin@example.com',
            password='pass12345',
        )
        MemberProfile.objects.create_user(
            username='KolyanghaM',
            email='other@example.com',
            password='pass12345',
        )
        with TemporaryDirectory() as directory:
            mapping_path = Path(directory) / 'mapping.csv'
            report_path = Path(directory) / 'report.csv'
            mapping_path.write_text(
                '\n'.join([
                    'old_username,new_username,email,name',
                    'kolyangha_martin_luther,KolyanghaM,martin@example.com,Kolyangha Martin Luther',
                ]),
                encoding='utf-8',
            )

            with self.assertRaises(CommandError):
                call_command(
                    'update_usernames_from_csv',
                    file=str(mapping_path),
                    report=str(report_path),
                    commit=True,
                )

            self.assertTrue(MemberProfile.objects.filter(username='kolyangha_martin_luther').exists())
            self.assertIn('already belongs to another user', report_path.read_text(encoding='utf-8'))
