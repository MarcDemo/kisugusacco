from datetime import date, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from deposits.models import DepositSubmission
from groupcore.models import MemberProfile, SavingsAccount
from incomes.models import AnnualSubscription, ShareContribution


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
        self.other_member = MemberProfile.objects.create_user(
            username='other-member',
            first_name='Beatrice',
            last_name='Member',
            password='pass12345',
            role='MEMBER',
        )
        self.other_account = SavingsAccount.objects.create(
            owner=self.other_member, label='B1'
        )

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

    def test_financial_records_allow_historical_deposits_without_submitter(self):
        self.previous_deposit.submitted_by = None
        self.previous_deposit.import_reference = 'historical-previous-deposit'
        self.previous_deposit.save(update_fields=['submitted_by', 'import_reference'])
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(reverse('other_income_list'), {'year': self.previous_year})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Historical Import')

    def test_regular_member_cannot_view_treasurer_financial_records(self):
        self.client.login(username='member', password='pass12345')

        response = self.client.get(reverse('other_income_list'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('member_dashboard'))

    def test_financial_records_are_paginated_ten_per_page(self):
        for day in range(3, 14):
            self._deposit(
                payment_week=date(self.current_year, 1, day),
                payment_date=date(self.current_year, 1, day),
                saving_amount=Decimal('1000'),
            )
        self.client.login(username='treasurer', password='pass12345')

        first_page = self.client.get(reverse('other_income_list'))
        second_page = self.client.get(reverse('other_income_list'), {'page': 2})

        self.assertEqual(len(first_page.context['financial_deposits']), 10)
        self.assertEqual(first_page.context['financial_deposits'].paginator.count, 12)
        self.assertEqual(len(second_page.context['financial_deposits']), 2)
        self.assertContains(
            first_page,
            f'?year={self.current_year}&amp;page=2',
        )

    def test_member_filter_applies_to_totals_deposits_and_manual_records(self):
        other_deposit = DepositSubmission.objects.create(
            member=self.other_member,
            account=self.other_account,
            submitted_by=self.treasurer,
            payment_week=date(self.current_year, 1, 9),
            payment_date=date(self.current_year, 1, 9),
            payment_time=time(9, 0),
            saving_amount=Decimal('70000'),
            status='APPROVED',
        )
        selected_share = ShareContribution.objects.create(
            member=self.member,
            account=self.account,
            amount=Decimal('15000'),
            recorded_by=self.treasurer,
        )
        ShareContribution.objects.create(
            member=self.other_member,
            account=self.other_account,
            amount=Decimal('25000'),
            recorded_by=self.treasurer,
        )
        selected_subscription = AnnualSubscription.objects.create(
            member=self.member,
            year=self.current_year,
            amount=Decimal('10000'),
            is_paid=True,
            recorded_by=self.treasurer,
        )
        AnnualSubscription.objects.create(
            member=self.other_member,
            year=self.current_year,
            amount=Decimal('10000'),
            is_paid=True,
            recorded_by=self.treasurer,
        )
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(
            reverse('other_income_list'),
            {'year': self.current_year, 'member': self.member.id},
        )

        self.assertEqual(response.context['selected_member'], self.member)
        self.assertEqual(
            list(response.context['financial_deposits']),
            [self.current_deposit],
        )
        self.assertNotIn(other_deposit, response.context['financial_deposits'])
        self.assertEqual(
            response.context['summary_totals']['saving'],
            Decimal('50000'),
        )
        self.assertEqual(response.context['summary_totals']['record_count'], 1)
        self.assertEqual(list(response.context['shares']), [selected_share])
        self.assertEqual(
            list(response.context['subscriptions']),
            [selected_subscription],
        )
        self.assertContains(response, 'member-filter-search')
        self.assertContains(response, 'Clear member')

    def test_all_members_and_invalid_member_restore_group_records(self):
        other_deposit = DepositSubmission.objects.create(
            member=self.other_member,
            account=self.other_account,
            submitted_by=self.treasurer,
            payment_week=date(self.current_year, 1, 9),
            payment_date=date(self.current_year, 1, 9),
            payment_time=time(9, 0),
            saving_amount=Decimal('70000'),
            status='APPROVED',
        )
        self.client.login(username='treasurer', password='pass12345')

        all_members = self.client.get(
            reverse('other_income_list'),
            {'year': self.current_year},
        )
        invalid_member = self.client.get(
            reverse('other_income_list'),
            {'year': self.current_year, 'member': 999999},
        )

        self.assertEqual(
            set(all_members.context['financial_deposits']),
            {self.current_deposit, other_deposit},
        )
        self.assertIsNone(invalid_member.context['selected_member'])
        self.assertEqual(
            set(invalid_member.context['financial_deposits']),
            {self.current_deposit, other_deposit},
        )
        self.assertEqual(
            invalid_member.context['summary_totals']['saving'],
            Decimal('120000'),
        )

    def test_member_choices_are_alphabetical_with_username_fallback(self):
        MemberProfile.objects.create_user(
            username='aaron-no-name', password='pass12345', role='MEMBER'
        )
        MemberProfile.objects.create_user(
            username='zulu-login',
            first_name='Zelda',
            last_name='Zulu',
            password='pass12345',
            role='MEMBER',
        )
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(reverse('other_income_list'))

        labels = [
            member.get_full_name().strip() or member.username
            for member in response.context['members']
        ]
        self.assertEqual(
            labels,
            sorted(labels, key=str.casefold),
        )

    def test_member_and_year_filters_survive_pagination(self):
        for day in range(3, 14):
            self._deposit(
                payment_week=date(self.current_year, 1, day),
                payment_date=date(self.current_year, 1, day),
                saving_amount=Decimal('1000'),
            )
        self.client.login(username='treasurer', password='pass12345')

        response = self.client.get(
            reverse('other_income_list'),
            {'year': self.current_year, 'member': self.member.id},
        )

        self.assertEqual(response.context['financial_deposits'].paginator.count, 12)
        self.assertContains(
            response,
            f'?year={self.current_year}&amp;member={self.member.id}&amp;page=2',
        )

    def test_chairman_can_filter_but_does_not_receive_edit_actions(self):
        chairman = MemberProfile.objects.create_user(
            username='records-chairman',
            password='pass12345',
            role='CHAIRMAN',
        )
        self.client.login(username=chairman.username, password='pass12345')

        response = self.client.get(
            reverse('other_income_list'),
            {'member': self.member.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.member.username)
        self.assertNotContains(
            response,
            reverse(
                'financial_record_edit',
                args=['deposit', self.current_deposit.id],
            ),
        )
