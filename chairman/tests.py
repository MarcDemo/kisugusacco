from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from deposits.models import DepositSubmission
from fines.models import Fine
from groupcore.models import (
    AccountSettlement,
    FinancialYearClose,
    FinancialYearLoanSnapshot,
    MemberProfile,
    SavingsAccount,
    SavingsAccountOwnershipTransfer,
    SettlementLoanAllocation,
    SettlementVersion,
)
from incomes.models import (
    AnnualSubscription,
    ShareContribution,
    WelfareLedger,
)
from loans.models import LoanRequest

from .services import make_account_dependent


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

    def test_secretary_can_make_linked_account_independent_with_history(self):
        owner = MemberProfile.objects.create_user(
            username='household',
            password='pass12345',
            role='MEMBER',
        )
        SavingsAccount.objects.create(owner=owner, label='Othieno Moses')
        account = SavingsAccount.objects.create(owner=owner, label='Sarah Othieno')
        deposit = DepositSubmission.objects.create(
            member=owner,
            account=account,
            submitted_by=self.secretary,
            payment_week=date(2026, 1, 2),
            starting_week=date(2026, 1, 2),
            weeks_covered=1,
            saving_amount=Decimal('50000.00'),
            proof='proofs/test.jpg',
            payment_date=date(2026, 1, 2),
            payment_time=time(9, 0),
            status='APPROVED',
        )
        fine = Fine.objects.create(
            member=owner,
            account=account,
            fine_type='MISSED_WEEKLY_SAVING',
            reference_week=date(2026, 1, 2),
            reason='Late weekly saving',
            amount=Decimal('2000.00'),
            issued_by=self.secretary,
        )
        share = ShareContribution.objects.create(
            member=owner,
            account=account,
            amount=Decimal('100000.00'),
            recorded_by=self.secretary,
        )
        loan = LoanRequest.objects.create(
            member=owner,
            account=account,
            principal=Decimal('100000.00'),
            status=LoanRequest.STATUS_PENDING,
        )

        self.client.login(username='secretary', password='pass12345')
        response = self.client.post(reverse('make_account_independent', args=[account.id]), {
            'username': 'SarahO',
            'full_name': 'Sarah Othieno',
            'phone_number': '+256 700 000001',
            'email': 'sarah@example.com',
            'password': 'memberpass123',
            'role': 'MEMBER',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        new_member = MemberProfile.objects.get(username='SarahO')
        account.refresh_from_db()
        deposit.refresh_from_db()
        fine.refresh_from_db()
        share.refresh_from_db()
        loan.refresh_from_db()
        self.assertEqual(account.owner, new_member)
        self.assertEqual(deposit.member, new_member)
        self.assertEqual(fine.member, new_member)
        self.assertEqual(share.member, new_member)
        self.assertEqual(loan.member, new_member)
        self.assertEqual(owner.savings_accounts.count(), 1)
        self.assertContains(response, 'SarahO')

    def test_make_independent_rejects_duplicate_email(self):
        owner = MemberProfile.objects.create_user(
            username='household',
            password='pass12345',
            role='MEMBER',
        )
        SavingsAccount.objects.create(owner=owner, label='Othieno Moses')
        account = SavingsAccount.objects.create(owner=owner, label='Sarah Othieno')
        MemberProfile.objects.create_user(
            username='existing',
            password='pass12345',
            email='sarah@example.com',
        )

        self.client.login(username='secretary', password='pass12345')
        response = self.client.post(reverse('make_account_independent', args=[account.id]), {
            'username': 'SarahO',
            'full_name': 'Sarah Othieno',
            'phone_number': '+256 700 000001',
            'email': 'sarah@example.com',
            'password': 'memberpass123',
            'role': 'MEMBER',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A user with this email address already exists.')
        account.refresh_from_db()
        self.assertEqual(account.owner, owner)

    def test_single_account_cannot_be_made_independent(self):
        owner = MemberProfile.objects.create_user(
            username='single',
            password='pass12345',
            role='MEMBER',
        )
        account = SavingsAccount.objects.create(owner=owner, label='Single Account')

        self.client.login(username='secretary', password='pass12345')
        response = self.client.get(reverse('make_account_independent', args=[account.id]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already the only account')


class MakeAccountDependentTests(TestCase):
    def setUp(self):
        self.chairman = MemberProfile.objects.create_user(
            username='dependent-chairman',
            password='pass12345',
            role='CHAIRMAN',
        )
        self.secretary = MemberProfile.objects.create_user(
            username='dependent-secretary',
            password='pass12345',
            role='SECRETARY',
        )
        self.treasurer = MemberProfile.objects.create_user(
            username='dependent-treasurer',
            password='pass12345',
            role='TREASURER',
        )
        self.source = MemberProfile.objects.create_user(
            username='independent-member',
            first_name='Independent',
            last_name='Member',
            password='pass12345',
            role='MEMBER',
        )
        self.account = SavingsAccount.objects.create(
            owner=self.source,
            label='Family Account',
        )
        self.target = MemberProfile.objects.create_user(
            username='receiving-member',
            first_name='Receiving',
            last_name='Member',
            password='pass12345',
            role='MEMBER',
        )

    def _post_transfer(self, **overrides):
        payload = {
            'target_member': str(self.target.pk),
            'reason': 'Consolidating the family savings accounts.',
            'confirm_transfer': 'on',
        }
        payload.update(overrides)
        return self.client.post(
            reverse('make_account_dependent', args=[self.account.pk]),
            payload,
        )

    def test_single_member_account_shows_dependent_action_on_management_pages(self):
        self.client.login(username=self.chairman.username, password='pass12345')

        edit_response = self.client.get(reverse('edit_user', args=[self.source.pk]))
        detail_response = self.client.get(reverse('user_detail', args=[self.source.pk]))

        transfer_url = reverse('make_account_dependent', args=[self.account.pk])
        self.assertContains(edit_response, 'Make Dependent')
        self.assertContains(edit_response, transfer_url)
        self.assertContains(detail_response, 'Make Dependent')
        self.assertContains(detail_response, transfer_url)

    def test_multi_account_and_leadership_profiles_show_dependent_action(self):
        SavingsAccount.objects.create(owner=self.source, label='Second Account')
        leadership_account = SavingsAccount.objects.create(
            owner=self.secretary,
            label='Secretary Account',
        )
        self.client.login(username=self.chairman.username, password='pass12345')

        multi_response = self.client.get(reverse('edit_user', args=[self.source.pk]))
        leadership_response = self.client.get(
            reverse('user_detail', args=[self.secretary.pk])
        )

        self.assertContains(multi_response, 'Make Dependent', count=2)
        self.assertContains(multi_response, 'Make Independent')
        self.assertContains(leadership_response, 'Make Dependent')
        self.assertContains(
            leadership_response,
            reverse('make_account_dependent', args=[leadership_account.pk]),
        )

    def test_leadership_last_account_transfer_keeps_login_active(self):
        leadership_account = SavingsAccount.objects.create(
            owner=self.secretary,
            label='Secretary Savings',
        )
        self.client.login(username=self.chairman.username, password='pass12345')

        response = self.client.post(
            reverse('make_account_dependent', args=[leadership_account.pk]),
            {
                'target_member': str(self.target.pk),
                'reason': 'Moving the office bearer savings account.',
                'confirm_transfer': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        leadership_account.refresh_from_db()
        self.secretary.refresh_from_db()
        self.assertEqual(leadership_account.owner, self.target)
        self.assertTrue(self.secretary.is_active)
        audit = SavingsAccountOwnershipTransfer.objects.get(
            account=leadership_account
        )
        self.assertFalse(audit.source_profile_deactivated)
        self.client.logout()
        self.assertTrue(
            self.client.login(
                username=self.secretary.username,
                password='pass12345',
            )
        )

    def test_superuser_account_cannot_be_made_dependent_by_direct_url(self):
        superuser = MemberProfile.objects.create_superuser(
            username='source-superuser',
            email='source-superuser@example.com',
            password='pass12345',
        )
        superuser_account = SavingsAccount.objects.create(
            owner=superuser,
            label='Administrative Account',
        )
        self.client.login(username=self.chairman.username, password='pass12345')

        response = self.client.get(
            reverse('make_account_dependent', args=[superuser_account.pk])
        )

        self.assertEqual(response.status_code, 302)
        superuser_account.refresh_from_db()
        superuser.refresh_from_db()
        self.assertEqual(superuser_account.owner, superuser)
        self.assertTrue(superuser.is_active)

    def test_target_choices_include_active_users_and_exclude_invalid_users(self):
        inactive = MemberProfile.objects.create_user(
            username='inactive-target',
            password='pass12345',
            is_active=False,
        )
        superuser = MemberProfile.objects.create_superuser(
            username='super-target',
            email='super@example.com',
            password='pass12345',
        )
        self.client.login(username=self.chairman.username, password='pass12345')

        response = self.client.get(
            reverse('make_account_dependent', args=[self.account.pk])
        )

        target_ids = set(
            response.context['form'].fields['target_member'].queryset.values_list(
                'id', flat=True
            )
        )
        self.assertIn(self.target.pk, target_ids)
        self.assertIn(self.secretary.pk, target_ids)
        self.assertNotIn(self.source.pk, target_ids)
        self.assertNotIn(inactive.pk, target_ids)
        self.assertNotIn(superuser.pk, target_ids)

    def test_chairman_secretary_and_treasurer_can_open_transfer_form(self):
        for manager in (self.chairman, self.secretary, self.treasurer):
            with self.subTest(role=manager.role):
                self.client.force_login(manager)
                response = self.client.get(
                    reverse('make_account_dependent', args=[self.account.pk])
                )
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_ordinary_member_cannot_transfer_an_account(self):
        outsider = MemberProfile.objects.create_user(
            username='dependent-outsider',
            password='pass12345',
            role='MEMBER',
        )
        SavingsAccount.objects.create(owner=outsider, label='Outsider Account')
        self.client.login(username=outsider.username, password='pass12345')

        response = self.client.get(
            reverse('make_account_dependent', args=[self.account.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.account.refresh_from_db()
        self.assertEqual(self.account.owner, self.source)

    def test_transfer_moves_account_history_settlements_and_deactivates_source(self):
        self.account.is_active = False
        self.account.save(update_fields=['is_active'])
        deposit = DepositSubmission.objects.create(
            member=self.source,
            account=self.account,
            submitted_by=self.chairman,
            reviewed_by=self.secretary,
            payment_week=date(2025, 6, 6),
            starting_week=date(2025, 6, 6),
            weeks_covered=1,
            saving_amount=Decimal('50000.00'),
            payment_date=date(2025, 6, 6),
            payment_time=time(9, 0),
            status='APPROVED',
        )
        fine = Fine.objects.create(
            member=self.source,
            account=self.account,
            fine_type='OTHER',
            reason='Late attendance',
            amount=Decimal('2000.00'),
            issued_by=self.chairman,
        )
        share = ShareContribution.objects.create(
            member=self.source,
            account=self.account,
            amount=Decimal('100000.00'),
            recorded_by=self.treasurer,
        )
        loan = LoanRequest.objects.create(
            member=self.source,
            account=self.account,
            principal=Decimal('200000.00'),
            status=LoanRequest.STATUS_APPROVED,
            treasurer_approved_by=self.treasurer,
        )
        subscription = AnnualSubscription.objects.create(
            member=self.source,
            year=2025,
            is_paid=True,
        )
        welfare = WelfareLedger.objects.create(
            member=self.source,
            year=2025,
        )
        financial_year = FinancialYearClose.objects.create(
            year=2025,
            scheduled_closing_date=date(2025, 12, 31),
            state=FinancialYearClose.STATE_FINALIZED,
            finalized_at=timezone.now(),
            finalized_by=self.chairman,
        )
        version = SettlementVersion.objects.create(
            financial_year=financial_year,
            version=1,
            created_by=self.chairman,
            cutoff_at=timezone.now(),
        )
        settlement = AccountSettlement.objects.create(
            settlement_version=version,
            account=self.account,
            member=self.source,
            savings_total=Decimal('50000.00'),
            net_payout=Decimal('50000.00'),
        )
        snapshot = FinancialYearLoanSnapshot.objects.create(
            financial_year=financial_year,
            loan=loan,
            frozen_balance=Decimal('200000.00'),
            frozen_at=timezone.now(),
        )
        allocation = SettlementLoanAllocation.objects.create(
            settlement_version=version,
            loan_snapshot=snapshot,
            allocation_type=SettlementLoanAllocation.TYPE_BORROWER,
            member=self.source,
            account=self.account,
            amount=Decimal('200000.00'),
        )
        self.client.login(username=self.chairman.username, password='pass12345')

        response = self._post_transfer()

        self.assertRedirects(
            response,
            reverse('user_detail', args=[self.target.pk]),
            fetch_redirect_response=False,
        )
        for record in (deposit, fine, share, loan, settlement, allocation):
            record.refresh_from_db()
            self.assertEqual(record.member, self.target)
        self.account.refresh_from_db()
        self.source.refresh_from_db()
        subscription.refresh_from_db()
        welfare.refresh_from_db()
        self.assertEqual(self.account.owner, self.target)
        self.assertFalse(self.account.is_active)
        self.assertFalse(self.source.is_active)
        self.assertEqual(subscription.member, self.source)
        self.assertEqual(welfare.member, self.source)
        self.assertEqual(deposit.submitted_by, self.chairman)
        self.assertEqual(deposit.reviewed_by, self.secretary)
        self.assertEqual(fine.issued_by, self.chairman)
        self.assertEqual(share.recorded_by, self.treasurer)
        self.assertEqual(loan.treasurer_approved_by, self.treasurer)

        audit = SavingsAccountOwnershipTransfer.objects.get(account=self.account)
        self.assertEqual(audit.old_owner, self.source)
        self.assertEqual(audit.new_owner, self.target)
        self.assertEqual(audit.transferred_by, self.chairman)
        self.assertEqual(audit.account_label, 'Family Account')
        self.assertTrue(audit.source_profile_deactivated)
        self.client.logout()
        self.assertFalse(
            self.client.login(
                username=self.source.username,
                password='pass12345',
            )
        )

    def test_reason_and_explicit_confirmation_are_required(self):
        self.client.login(username=self.chairman.username, password='pass12345')

        response = self._post_transfer(reason='', confirm_transfer='')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required', count=2)
        self.account.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(self.account.owner, self.source)
        self.assertTrue(self.source.is_active)
        self.assertFalse(SavingsAccountOwnershipTransfer.objects.exists())

    def test_duplicate_target_label_blocks_transfer_case_insensitively(self):
        SavingsAccount.objects.create(
            owner=self.target,
            label='family account',
        )
        self.client.login(username=self.chairman.username, password='pass12345')

        response = self._post_transfer()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already has a savings account named')
        self.account.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(self.account.owner, self.source)
        self.assertTrue(self.source.is_active)
        self.assertFalse(SavingsAccountOwnershipTransfer.objects.exists())

    def test_multi_account_transfer_keeps_source_login_and_remaining_account(self):
        remaining_account = SavingsAccount.objects.create(
            owner=self.source,
            label='Remaining Account',
        )
        self.client.login(username=self.chairman.username, password='pass12345')

        response = self._post_transfer()

        self.assertEqual(response.status_code, 302)
        self.account.refresh_from_db()
        remaining_account.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(self.account.owner, self.target)
        self.assertEqual(remaining_account.owner, self.source)
        self.assertTrue(self.source.is_active)
        audit = SavingsAccountOwnershipTransfer.objects.get(account=self.account)
        self.assertFalse(audit.source_profile_deactivated)
        self.client.logout()
        self.assertTrue(
            self.client.login(
                username=self.source.username,
                password='pass12345',
            )
        )

    def test_transaction_rolls_back_if_audit_creation_fails(self):
        deposit = DepositSubmission.objects.create(
            member=self.source,
            account=self.account,
            submitted_by=self.chairman,
            payment_week=date(2026, 1, 2),
            starting_week=date(2026, 1, 2),
            saving_amount=Decimal('50000.00'),
            payment_date=date(2026, 1, 2),
            payment_time=time(9, 0),
        )

        with patch(
            'chairman.services.SavingsAccountOwnershipTransfer.objects.create',
            side_effect=RuntimeError('simulated audit failure'),
        ):
            with self.assertRaisesMessage(RuntimeError, 'simulated audit failure'):
                make_account_dependent(
                    account_id=self.account.pk,
                    target_member_id=self.target.pk,
                    transferred_by=self.chairman,
                    reason='Testing complete transaction rollback.',
                )

        self.account.refresh_from_db()
        self.source.refresh_from_db()
        deposit.refresh_from_db()
        self.assertEqual(self.account.owner, self.source)
        self.assertEqual(deposit.member, self.source)
        self.assertTrue(self.source.is_active)
        self.assertFalse(SavingsAccountOwnershipTransfer.objects.exists())


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
