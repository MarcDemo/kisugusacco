from datetime import date, time, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from deposits.models import DepositSubmission
from deposits.forms import DepositSubmissionForm, DirectDepositForm
from fines.models import Fine
from groupcore.account_context import SESSION_KEY_ACTIVE_ACCOUNT
from groupcore.models import GroupSettings, MemberProfile, SavingsAccount
from groupcore.week_cycle import current_saving_week
from loans.models import LoanRequest


class VariableWeeklySavingsAllocationTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        first_day = date(today.year, 1, 1)
        first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
        GroupSettings.objects.create(week_one_start=first_friday)
        self.saving_week = current_saving_week(first_friday, today)
        self.treasurer = MemberProfile.objects.create_user(
            username='variable-treasurer', password='pass12345', role='TREASURER'
        )
        self.member = MemberProfile.objects.create_user(
            username='variable-member', password='pass12345', role='MEMBER'
        )
        self.account = SavingsAccount.objects.create(owner=self.member, label='A')

    def direct_data(self, weeks, amounts, amount_received=None):
        data = QueryDict('', mutable=True)
        data.update({
            'member': str(self.member.id),
            'account': str(self.account.id),
            'payment_date': timezone.localdate().isoformat(),
            'payment_time': '10:00',
        })
        data.setlist('selected_purposes', ['saving'])
        data.setlist('selected_weeks', [week.isoformat() for week in weeks])
        for week, amount in zip(weeks, amounts):
            data[f'week_amount_{week.isoformat()}'] = str(amount)
        if amount_received is not None:
            data['amount_received'] = str(amount_received)
        return data

    def test_each_boundary_and_midrange_weekly_amount_is_valid(self):
        week = self.saving_week.cycle_start
        for amount in (10000, 30000, 50000):
            with self.subTest(amount=amount):
                form = DirectDepositForm(self.direct_data([week], [amount], amount))
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['weekly_allocations'], [(week, Decimal(amount))])

    def test_below_minimum_and_above_maximum_are_rejected(self):
        week = self.saving_week.cycle_start
        for amount in (9999, 50001):
            with self.subTest(amount=amount):
                form = DirectDepositForm(self.direct_data([week], [amount], amount))
                self.assertFalse(form.is_valid())
                self.assertIn('selected_weeks', form.errors)

    def test_treasurer_can_allocate_different_amounts_to_multiple_weeks(self):
        weeks = [self.saving_week.cycle_start, self.saving_week.cycle_start + timedelta(weeks=1)]
        data = self.direct_data(weeks, [20000, 10000], 30000)
        post_data = data.dict()
        post_data['selected_purposes'] = ['saving']
        post_data['selected_weeks'] = [week.isoformat() for week in weeks]
        self.client.login(username=self.treasurer.username, password='pass12345')

        response = self.client.post(reverse('manage_deposits'), post_data)

        self.assertEqual(response.status_code, 302, response.context['form'].errors if response.context else '')
        self.assertRedirects(response, reverse('manage_deposits'))
        saved = list(DepositSubmission.objects.filter(member=self.member).order_by('payment_week'))
        self.assertEqual([item.saving_amount for item in saved], [Decimal('20000'), Decimal('10000')])
        self.assertEqual(sum((item.amount for item in saved), Decimal('0')), Decimal('30000'))

    def test_paid_week_is_locked_and_duplicate_selection_is_rejected(self):
        week = self.saving_week.cycle_start
        DepositSubmission.objects.create(
            member=self.member, account=self.account, submitted_by=self.treasurer,
            payment_week=week, saving_amount=Decimal('10000'),
            payment_date=week, payment_time=time(9, 0), status='APPROVED',
        )
        locked_form = DirectDepositForm(self.direct_data([week], [30000], 30000))
        self.assertFalse(locked_form.is_valid())
        self.assertContainsError(locked_form, 'already paid and locked')

        duplicate_data = self.direct_data([week + timedelta(weeks=1)] * 2, [10000, 10000], 20000)
        duplicate_form = DirectDepositForm(duplicate_data)
        self.assertFalse(duplicate_form.is_valid())
        self.assertContainsError(duplicate_form, 'Select each week only once')

    def assertContainsError(self, form, text):
        self.assertIn(text, str(form.errors))

    def test_member_form_enforces_same_range_and_pending_lock(self):
        week = self.saving_week.week_start
        base = QueryDict('', mutable=True)
        base.update({
            'account': str(self.account.id), 'payment_date': timezone.localdate().isoformat(),
            'payment_time': '10:00', 'saving_amount': '10000',
        })
        base.setlist('selected_purposes', ['saving'])
        valid = DepositSubmissionForm(base, user=self.member, payment_week=week)
        self.assertTrue(valid.is_valid(), valid.errors)

        too_low = base.copy()
        too_low['saving_amount'] = '9999'
        self.assertFalse(DepositSubmissionForm(too_low, user=self.member, payment_week=week).is_valid())

        DepositSubmission.objects.create(
            member=self.member, account=self.account, submitted_by=self.member,
            payment_week=week, saving_amount=Decimal('10000'),
            payment_date=week, payment_time=time(9, 0), status='PENDING',
        )
        locked = DepositSubmissionForm(base, user=self.member, payment_week=week)
        self.assertFalse(locked.is_valid())
        self.assertContainsError(locked, 'already paid or awaiting approval')

    def test_manage_page_and_status_api_expose_week_allocations_and_locking(self):
        week = self.saving_week.cycle_start
        DepositSubmission.objects.create(
            member=self.member, account=self.account, submitted_by=self.treasurer,
            payment_week=week, saving_amount=Decimal('10000'),
            payment_date=week, payment_time=time(9, 0), status='APPROVED',
        )
        self.client.login(username=self.treasurer.username, password='pass12345')

        page = self.client.get(reverse('manage_deposits'))
        api = self.client.get(reverse('treasurer_week_options'), {
            'member': self.member.id, 'account': self.account.id,
        })

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'UGX 10,000–50,000')
        self.assertContains(page, 'week_amount_')
        self.assertEqual(api.status_code, 200)
        week_status = next(item for item in api.json()['weeks'] if item['date'] == week.isoformat())
        self.assertTrue(week_status['paid'])

    def test_unallocated_received_amount_is_rejected(self):
        week = self.saving_week.cycle_start
        form = DirectDepositForm(self.direct_data([week], [10000], 30000))
        self.assertFalse(form.is_valid())
        self.assertContainsError(form, 'overpayment')


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

    def test_treasurer_report_ignores_approved_loans_without_approval_date_in_year_options(self):
        LoanRequest.objects.create(
            member=self.member,
            principal=Decimal('100000.00'),
            monthly_interest_rate=Decimal('2.00'),
            status=LoanRequest.STATUS_APPROVED,
            approved_on=None,
        )
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(reverse('treasurer_reports'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.current_year, response.context['years'])

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


class CurrentWeekStatusExportTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 5)
        self.monday_after_grace = date(2026, 7, 6)
        self.week_one_start = date(2026, 1, 2)
        GroupSettings.objects.create(week_one_start=self.week_one_start)
        self.treasurer = MemberProfile.objects.create_user(
            username='treasurer',
            password='pass12345',
            role='TREASURER',
        )
        self.member = MemberProfile.objects.create_user(
            username='member',
            password='pass12345',
            role='MEMBER',
            first_name='Test',
            last_name='Member',
        )
        self.account = SavingsAccount.objects.create(owner=self.member, label='A1')
        self.unpaid_member = MemberProfile.objects.create_user(
            username='unpaid_member',
            password='pass12345',
            role='MEMBER',
            first_name='Late',
            last_name='Member',
        )
        self.unpaid_account = SavingsAccount.objects.create(owner=self.unpaid_member, label='B1')
        saving_week = current_saving_week(self.week_one_start, self.today)
        DepositSubmission.objects.create(
            member=self.member,
            account=self.account,
            submitted_by=self.member,
            payment_week=saving_week.week_start,
            starting_week=saving_week.week_start,
            weeks_covered=1,
            saving_amount=Decimal('50000.00'),
            proof='proofs/test.jpg',
            payment_date=saving_week.week_start,
            payment_time=time(9, 0),
            status='APPROVED',
        )

    def test_current_week_status_page_lists_account_level_statuses(self):
        self.client.login(username='treasurer', password='pass12345')

        with patch('deposits.views.timezone.localdate', return_value=self.today):
            response = self.client.get(reverse('current_week_status'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Paid Accounts')
        self.assertContains(response, 'Test Member')
        self.assertContains(response, 'A1')

    def test_current_week_status_does_not_create_fines_before_monday_after_grace(self):
        self.client.login(username='treasurer', password='pass12345')

        with patch('deposits.views.timezone.localdate', return_value=self.today):
            response = self.client.get(reverse('current_week_status'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Late Member')
        self.assertEqual(Fine.objects.count(), 0)

    def test_current_week_status_creates_fines_after_sunday_closes(self):
        self.client.login(username='treasurer', password='pass12345')

        with patch('deposits.views.timezone.localdate', return_value=self.monday_after_grace):
            response = self.client.get(reverse('current_week_status'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Fine.objects.filter(
                member=self.unpaid_member,
                account=self.unpaid_account,
                fine_type='MISSED_WEEKLY_SAVING',
            ).exists()
        )

    def test_current_week_status_export_excel_includes_account_status(self):
        self.client.login(username='treasurer', password='pass12345')

        with patch('deposits.views.timezone.localdate', return_value=self.today):
            response = self.client.get(reverse('export_current_week_status', args=['excel']))

        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        values = list(workbook.active.values)
        flattened = [cell for row in values for cell in row]
        self.assertIn('Test Member', flattened)
        self.assertIn('A1', flattened)
        self.assertIn('Paid', flattened)

    def test_current_week_status_export_pdf_returns_pdf(self):
        self.client.login(username='treasurer', password='pass12345')

        with patch('deposits.views.timezone.localdate', return_value=self.today):
            response = self.client.get(reverse('export_current_week_status', args=['pdf']))

        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response['Content-Disposition'].endswith('.pdf"'))
