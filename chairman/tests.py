from datetime import date, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from deposits.models import DepositSubmission
from groupcore.models import MemberProfile, SavingsAccount


class SecretaryUserManagementTests(TestCase):
    def setUp(self):
        self.secretary = MemberProfile.objects.create_user(
            username='secretary',
            password='pass12345',
            role='SECRETARY',
        )

    def test_secretary_can_create_user_with_savings_accounts(self):
        self.client.login(username='secretary', password='pass12345')

        response = self.client.post(reverse('add_user'), {
            'username': 'newmember',
            'first_name': 'New',
            'last_name': 'Member',
            'email': 'newmember@example.com',
            'phone_number': '+256 700 000000',
            'role': 'MEMBER',
            'password': 'memberpass123',
            'account_labels': 'A\nB',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        member = MemberProfile.objects.get(username='newmember')
        self.assertEqual(
            list(member.savings_accounts.order_by('label').values_list('label', flat=True)),
            ['A', 'B'],
        )

    def test_manage_users_includes_logged_in_secretary(self):
        self.client.login(username='secretary', password='pass12345')

        response = self.client.get(reverse('manage_users'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'secretary')
        self.assertContains(response, 'You')

    def test_manage_users_search_filters_by_name_and_account(self):
        target = MemberProfile.objects.create_user(
            username='markdemo',
            password='pass12345',
            role='MEMBER',
            first_name='Mark',
            last_name='Demo',
            email='mark@example.com',
        )
        SavingsAccount.objects.create(owner=target, label='Kisugu Special')
        MemberProfile.objects.create_user(
            username='othermember',
            password='pass12345',
            role='MEMBER',
            first_name='Other',
            last_name='Member',
        )
        self.client.login(username='secretary', password='pass12345')

        response = self.client.get(reverse('manage_users'), {'q': 'special'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'markdemo')
        self.assertNotContains(response, 'othermember')
        self.assertEqual(response.context['search_query'], 'special')

    def test_add_user_page_uses_account_label_builder(self):
        self.client.login(username='secretary', password='pass12345')

        response = self.client.get(reverse('add_user'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-account-label-builder')
        self.assertContains(response, 'Add Account')
        self.assertContains(response, 'type="hidden" name="account_labels"')

    def test_comma_separated_account_labels_are_rejected(self):
        self.client.login(username='secretary', password='pass12345')

        response = self.client.post(reverse('add_user'), {
            'username': 'newmember',
            'first_name': 'New',
            'last_name': 'Member',
            'email': 'newmember@example.com',
            'phone_number': '+256 700 000000',
            'role': 'MEMBER',
            'password': 'memberpass123',
            'account_labels': 'A,B',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add one savings account at a time using the Add account button.')
        self.assertFalse(MemberProfile.objects.filter(username='newmember').exists())

    def test_secretary_can_view_and_edit_user_accounts(self):
        member = MemberProfile.objects.create_user(
            username='member',
            password='pass12345',
            role='MEMBER',
            email='member@example.com',
        )
        account = SavingsAccount.objects.create(owner=member, label='A')

        self.client.login(username='secretary', password='pass12345')
        detail_response = self.client.get(reverse('user_detail', args=[member.id]))
        self.assertEqual(detail_response.status_code, 200)

        response = self.client.post(reverse('edit_user', args=[member.id]), {
            'username': 'member',
            'first_name': 'Edited',
            'last_name': 'Member',
            'email': 'edited@example.com',
            'phone_number': '+256 701 000000',
            'role': 'MEMBER',
            'password': '',
            'account_labels': 'B',
            'active_accounts': [str(account.id)],
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.first_name, 'Edited')
        self.assertTrue(SavingsAccount.objects.get(owner=member, label='A').is_active)
        self.assertTrue(SavingsAccount.objects.get(owner=member, label='B').is_active)


class ChairmanDepositReportYearFilterTests(TestCase):
    def setUp(self):
        self.current_year = timezone.localdate().year
        self.previous_year = self.current_year - 1
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
        self.previous_deposit = self._deposit(
            payment_week=date(self.previous_year, 12, 29),
            payment_date=date(self.current_year, 1, 2),
            saving_amount=Decimal('15000.00'),
        )
        self.current_deposit = self._deposit(
            payment_week=date(self.current_year, 1, 5),
            payment_date=date(self.current_year, 1, 5),
            saving_amount=Decimal('25000.00'),
        )

    def _deposit(self, payment_week, payment_date, saving_amount):
        return DepositSubmission.objects.create(
            member=self.member,
            submitted_by=self.chairman,
            payment_week=payment_week,
            starting_week=payment_week,
            weeks_covered=1,
            saving_amount=saving_amount,
            proof='proofs/test.jpg',
            payment_date=payment_date,
            payment_time=time(9, 0),
            status='APPROVED',
        )

    def test_chairman_deposit_report_filters_by_payment_week_year(self):
        self.client.login(username='chairman', password='pass12345')

        response = self.client.get(
            reverse('chairman_deposit_report'),
            {'year': self.previous_year},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_year'], self.previous_year)
        deposits = list(response.context['deposits'])
        self.assertIn(self.previous_deposit, deposits)
        self.assertNotIn(self.current_deposit, deposits)

    def test_chairman_deposit_report_defaults_to_current_year(self):
        self.client.login(username='chairman', password='pass12345')

        response = self.client.get(reverse('chairman_deposit_report'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_year'], self.current_year)
        deposits = list(response.context['deposits'])
        self.assertIn(self.current_deposit, deposits)
        self.assertNotIn(self.previous_deposit, deposits)
