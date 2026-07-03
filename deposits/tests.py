from datetime import date, time
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from deposits.models import DepositSubmission
from groupcore.account_context import SESSION_KEY_ACTIVE_ACCOUNT
from groupcore.models import MemberProfile, SavingsAccount


class TreasurerReportYearFilterTests(TestCase):
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
        self.previous_deposit = self._deposit(
            payment_week=date(self.previous_year, 12, 29),
            payment_date=date(self.current_year, 1, 2),
            saving_amount=Decimal('10000.00'),
        )
        self.current_deposit = self._deposit(
            payment_week=date(self.current_year, 1, 5),
            payment_date=date(self.current_year, 1, 5),
            saving_amount=Decimal('50000.00'),
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

    def _member_row(self, response):
        return next(
            row for row in response.context['report_data']
            if row['member'].id == self.member.id
        )

    def test_treasurer_report_filters_totals_by_selected_payment_week_year(self):
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(reverse('treasurer_reports'), {'year': self.previous_year})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_year'], self.previous_year)
        row = self._member_row(response)
        self.assertEqual(row['total_saving'], Decimal('10000'))
        self.assertEqual(row['total_amount'], Decimal('10000'))
        self.assertEqual(row['total_weeks'], 1)

    def test_treasurer_report_defaults_to_current_year(self):
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(reverse('treasurer_reports'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_year'], self.current_year)
        row = self._member_row(response)
        self.assertEqual(row['total_saving'], Decimal('50000'))
        self.assertEqual(row['total_amount'], Decimal('50000'))
        self.assertEqual(row['total_weeks'], 1)

    def test_member_export_filenames_include_selected_year(self):
        pdf_response = self.client.get(
            reverse('download_member_report', args=[self.member.id, 'pdf']),
            {'year': self.previous_year},
        )
        excel_response = self.client.get(
            reverse('download_member_report', args=[self.member.id, 'excel']),
            {'year': self.previous_year},
        )

        self.assertIn(
            f'{self.member.username}_report_{self.previous_year}.pdf',
            pdf_response['Content-Disposition'],
        )
        self.assertIn(
            f'{self.member.username}_report_{self.previous_year}.xlsx',
            excel_response['Content-Disposition'],
        )

    def test_all_member_excel_export_uses_selected_payment_week_year(self):
        response = self.client.get(
            reverse('download_all_reports', args=['excel']),
            {'year': self.previous_year},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'all_member_reports_{self.previous_year}.xlsx',
            response['Content-Disposition'],
        )
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        values = [
            value
            for row in workbook.active.iter_rows(values_only=True)
            for value in row
        ]
        self.assertIn(self.previous_deposit.payment_week.strftime('%Y-%m-%d'), values)
        self.assertNotIn(self.current_deposit.payment_week.strftime('%Y-%m-%d'), values)


class MyContributionsAccountExportTests(TestCase):
    def setUp(self):
        self.current_year = timezone.localdate().year
        self.previous_year = self.current_year - 1
        self.member = MemberProfile.objects.create_user(
            username='member_account_owner',
            password='pass12345',
            role='MEMBER',
        )
        self.other_member = MemberProfile.objects.create_user(
            username='other_member',
            password='pass12345',
            role='MEMBER',
        )
        self.account_a1 = SavingsAccount.objects.create(owner=self.member, label='A1')
        self.account_a2 = SavingsAccount.objects.create(owner=self.member, label='A2')
        self.other_account = SavingsAccount.objects.create(owner=self.other_member, label='A2')

        self.a2_previous_approved = self._deposit(
            member=self.member,
            account=self.account_a2,
            payment_week=date(self.previous_year, 12, 29),
            payment_date=date(self.current_year, 1, 2),
            saving_amount=Decimal('100.00'),
            status='APPROVED',
        )
        self.a2_previous_pending = self._deposit(
            member=self.member,
            account=self.account_a2,
            payment_week=date(self.previous_year, 12, 29),
            payment_date=date(self.previous_year, 12, 30),
            saving_amount=Decimal('200.00'),
            status='PENDING',
        )
        self.a2_previous_rejected = self._deposit(
            member=self.member,
            account=self.account_a2,
            payment_week=date(self.previous_year, 12, 29),
            payment_date=date(self.previous_year, 12, 31),
            saving_amount=Decimal('300.00'),
            status='REJECTED',
        )
        self.a2_current = self._deposit(
            member=self.member,
            account=self.account_a2,
            payment_week=date(self.current_year, 1, 5),
            payment_date=date(self.current_year, 1, 5),
            saving_amount=Decimal('400.00'),
            status='APPROVED',
        )
        self.a1_previous = self._deposit(
            member=self.member,
            account=self.account_a1,
            payment_week=date(self.previous_year, 12, 29),
            payment_date=date(self.previous_year, 12, 29),
            saving_amount=Decimal('500.00'),
            status='APPROVED',
        )
        self.other_previous = self._deposit(
            member=self.other_member,
            account=self.other_account,
            payment_week=date(self.previous_year, 12, 29),
            payment_date=date(self.previous_year, 12, 29),
            saving_amount=Decimal('600.00'),
            status='APPROVED',
        )

    def _deposit(self, member, account, payment_week, payment_date, saving_amount, status):
        return DepositSubmission.objects.create(
            member=member,
            account=account,
            submitted_by=member,
            payment_week=payment_week,
            starting_week=payment_week,
            weeks_covered=1,
            saving_amount=saving_amount,
            proof='proofs/test.jpg',
            payment_date=payment_date,
            payment_time=time(9, 0),
            status=status,
        )

    def _login_with_active_account(self, account):
        self.client.login(username='member_account_owner', password='pass12345')
        session = self.client.session
        session[SESSION_KEY_ACTIVE_ACCOUNT] = account.id
        session.save()

    def test_my_contributions_page_filters_active_account_by_payment_week_year(self):
        self._login_with_active_account(self.account_a2)

        response = self.client.get(reverse('my_contributions'), {'year': self.previous_year})

        self.assertEqual(response.status_code, 200)
        deposits = list(response.context['deposits'])
        self.assertIn(self.a2_previous_approved, deposits)
        self.assertIn(self.a2_previous_pending, deposits)
        self.assertIn(self.a2_previous_rejected, deposits)
        self.assertNotIn(self.a2_current, deposits)
        self.assertNotIn(self.a1_previous, deposits)
        self.assertNotIn(self.other_previous, deposits)
        self.assertEqual(response.context['approved_totals']['total'], Decimal('100'))

    def test_my_contributions_defaults_to_current_year(self):
        self._login_with_active_account(self.account_a2)

        response = self.client.get(reverse('my_contributions'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_year'], self.current_year)
        self.assertIn(self.current_year, response.context['years'])
        deposits = list(response.context['deposits'])
        self.assertIn(self.a2_current, deposits)
        self.assertNotIn(self.a2_previous_approved, deposits)
        self.assertNotIn(self.a2_previous_pending, deposits)
        self.assertNotIn(self.a2_previous_rejected, deposits)

    def test_excel_export_matches_active_account_filter_and_approved_totals(self):
        self._login_with_active_account(self.account_a2)

        response = self.client.get(
            reverse('export_my_contributions', args=['excel']),
            {'year': self.previous_year},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertIn(
            f'my_contributions_A2_{self.previous_year}.xlsx',
            response['Content-Disposition'],
        )
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        sheet = workbook.active
        values = [
            value
            for row in sheet.iter_rows(values_only=True)
            for value in row
        ]

        self.assertEqual(sheet['A12'].value, 100)
        self.assertIn('Pending', values)
        self.assertIn('Rejected', values)
        self.assertIn(self.a2_previous_approved.payment_week.strftime('%Y-%m-%d'), values)
        self.assertNotIn('A1', values)
        self.assertNotIn('other_member', values)
        self.assertNotIn(self.a2_current.payment_week.strftime('%Y-%m-%d'), values)

    def test_excel_export_defaults_to_current_year(self):
        self._login_with_active_account(self.account_a2)

        response = self.client.get(reverse('export_my_contributions', args=['excel']))

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'my_contributions_A2_{self.current_year}.xlsx',
            response['Content-Disposition'],
        )
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        sheet = workbook.active
        values = [
            value
            for row in sheet.iter_rows(values_only=True)
            for value in row
        ]
        self.assertEqual(sheet['A12'].value, 400)
        self.assertIn(self.a2_current.payment_week.strftime('%Y-%m-%d'), values)
        self.assertNotIn(self.a2_previous_approved.payment_week.strftime('%Y-%m-%d'), values)

    def test_pdf_export_uses_active_account_filename(self):
        self._login_with_active_account(self.account_a2)

        response = self.client.get(
            reverse('export_my_contributions', args=['pdf']),
            {'year': self.previous_year},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(
            f'my_contributions_A2_{self.previous_year}.pdf',
            response['Content-Disposition'],
        )

    def test_invalid_year_export_defaults_to_current_year(self):
        self._login_with_active_account(self.account_a2)

        response = self.client.get(
            reverse('export_my_contributions', args=['excel']),
            {'year': 'bad-year'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'my_contributions_A2_{self.current_year}.xlsx',
            response['Content-Disposition'],
        )
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        self.assertEqual(workbook.active['A12'].value, 400)

    def test_empty_excel_export_is_valid_with_zero_approved_totals_for_selected_year(self):
        self._login_with_active_account(self.account_a2)

        response = self.client.get(
            reverse('export_my_contributions', args=['excel']),
            {'year': 1900},
        )

        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        self.assertEqual(workbook.active['A12'].value, 0)
