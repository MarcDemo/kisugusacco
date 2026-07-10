from datetime import date, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from deposits.models import DepositSubmission
from groupcore.models import MemberProfile, SavingsAccount


class FinancialRecordsViewTests(TestCase):
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
        self.account = SavingsAccount.objects.create(owner=self.member, label='A1')

        self.current_deposit = self._deposit(
            payment_week=date(self.current_year, 1, 2),
            payment_date=date(self.current_year, 1, 2),
            saving_amount=Decimal('50000'),
            welfare_amount=Decimal('1000'),
            annual_subscription_amount=Decimal('10000'),
            membership_amount=Decimal('5000'),
            fine_amount=Decimal('2000'),
            shares_amount=Decimal('100000'),
            loan_repayment_amount=Decimal('25000'),
        )
        self.previous_deposit = self._deposit(
            payment_week=date(self.previous_year, 1, 3),
            payment_date=date(self.current_year, 1, 4),
            saving_amount=Decimal('30000'),
            welfare_amount=Decimal('1000'),
        )

    def _deposit(self, payment_week, payment_date, **amounts):
        return DepositSubmission.objects.create(
            member=self.member,
            account=self.account,
            submitted_by=self.treasurer,
            payment_week=payment_week,
            starting_week=payment_week,
            weeks_covered=1,
            proof='proofs/test.jpg',
            payment_date=payment_date,
            payment_time=time(9, 0),
            status='APPROVED',
            **amounts,
        )

    def test_financial_records_default_to_current_saving_year_deposits(self):
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(reverse('other_income_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_year'], self.current_year)
        self.assertEqual(list(response.context['financial_deposits']), [self.current_deposit])
        self.assertEqual(response.context['summary_totals']['saving'], Decimal('50000'))
        self.assertEqual(response.context['summary_totals']['membership'], Decimal('5000'))
        self.assertEqual(response.context['summary_totals']['loan_repayment'], Decimal('25000'))

    def test_financial_records_filter_by_selected_payment_week_year(self):
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(reverse('other_income_list'), {'year': self.previous_year})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_year'], self.previous_year)
        self.assertEqual(list(response.context['financial_deposits']), [self.previous_deposit])
        self.assertEqual(response.context['summary_totals']['saving'], Decimal('30000'))
        self.assertEqual(response.context['summary_totals']['welfare'], Decimal('1000'))

    def test_regular_member_cannot_view_treasurer_financial_records(self):
        self.client.login(username='member', password='pass12345')

        response = self.client.get(reverse('other_income_list'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('member_dashboard'))
