from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from deposits.models import DepositSubmission
from groupcore.models import GroupSettings, MemberProfile, SavingsAccount
from loans.models import LoanRequest

from .models import Withdrawal
from .services import account_balance, create_withdrawal, edit_withdrawal, void_withdrawal


class WithdrawalServiceTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        first_day = date(today.year, 1, 1)
        first_friday = first_day.replace(
            day=first_day.day + ((4 - first_day.weekday()) % 7)
        )
        GroupSettings.objects.create(week_one_start=first_friday)
        self.member = MemberProfile.objects.create_user(
            username='member-one', password='secret', role='MEMBER'
        )
        self.treasurer = MemberProfile.objects.create_user(
            username='treasurer-one', password='secret', role='TREASURER'
        )
        self.account = SavingsAccount.objects.create(owner=self.member, label='Main')
        DepositSubmission.objects.create(
            member=self.member,
            account=self.account,
            payment_week=first_friday,
            saving_amount=Decimal('100000.00'),
            amount=Decimal('100000.00'),
            payment_date=today,
            payment_time=timezone.localtime().time(),
            status='APPROVED',
            submitted_by=self.member,
        )

    def data(self, amount='30000.00'):
        return {
            'account': self.account,
            'amount': Decimal(amount),
            'withdrawn_on': timezone.localdate(),
            'reason': 'Emergency household expense',
            'reference': 'REQ-001',
            'notes': '',
        }

    def test_create_edit_and_void_keep_audited_balances(self):
        item = create_withdrawal(data=self.data(), user=self.treasurer)
        self.assertEqual(account_balance(self.account)['net'], Decimal('70000.00'))

        changed = self.data('40000.00')
        changed['reference'] = 'REQ-001-CORRECTED'
        edit_withdrawal(
            withdrawal_id=item.pk,
            data=changed,
            user=self.treasurer,
            correction_reason='Corrected amount from payment receipt',
        )
        item.refresh_from_db()
        self.assertEqual(item.amount, Decimal('40000.00'))
        self.assertEqual(item.revisions.count(), 1)
        self.assertEqual(item.revisions.get().before_data['amount'], '30000.00')
        self.assertEqual(account_balance(self.account)['net'], Decimal('60000.00'))

        void_withdrawal(
            withdrawal_id=item.pk,
            user=self.treasurer,
            reason='Payment was cancelled before collection',
        )
        item.refresh_from_db()
        self.assertTrue(item.is_voided)
        self.assertEqual(item.revisions.count(), 2)
        self.assertEqual(account_balance(self.account)['net'], Decimal('100000.00'))

    def test_loan_hold_blocks_unsafe_withdrawal(self):
        LoanRequest.objects.create(
            member=self.member,
            account=self.account,
            principal=Decimal('60000.00'),
            monthly_interest_rate=Decimal('0.00'),
            status=LoanRequest.STATUS_APPROVED,
            approved_on=timezone.now(),
        )
        balance = account_balance(self.account)
        self.assertEqual(balance['borrower_hold'], Decimal('60000.00'))
        with self.assertRaises(ValidationError):
            create_withdrawal(data=self.data('50000.00'), user=self.treasurer)
        self.assertFalse(Withdrawal.objects.exists())

    def test_non_treasurer_cannot_record_withdrawal(self):
        with self.assertRaisesMessage(Exception, 'Only the Treasurer'):
            create_withdrawal(data=self.data(), user=self.member)


class WithdrawalViewPermissionTests(TestCase):
    def test_treasurer_can_open_ledger_and_form(self):
        treasurer = MemberProfile.objects.create_user(
            username='screen-treasurer', password='secret', role='TREASURER'
        )
        self.client.force_login(treasurer)
        self.assertEqual(self.client.get('/withdrawals/').status_code, 200)
        self.assertEqual(self.client.get('/withdrawals/new/').status_code, 200)

    def test_member_cannot_open_treasurer_ledger(self):
        member = MemberProfile.objects.create_user(
            username='ordinary-member', password='secret', role='MEMBER'
        )
        self.client.force_login(member)
        response = self.client.get('/withdrawals/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/member/dashboard/')

