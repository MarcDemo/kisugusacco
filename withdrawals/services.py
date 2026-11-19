from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from deposits.models import DepositSubmission
from groupcore.models import GroupSettings, SavingsAccount
from groupcore.week_cycle import current_saving_week
from groupcore.year_close import submissions_locked_for_year
from loans.models import LoanGuarantorApproval, LoanRequest
from messaging.services import send_notification

from .models import Withdrawal, WithdrawalRevision


ZERO = Decimal('0.00')


def active_saving_year(on_date=None):
    on_date = on_date or timezone.localdate()
    settings = GroupSettings.get_active()
    return (
        current_saving_week(settings.week_one_start, on_date).saving_year
        if settings else on_date.year
    )


def ensure_withdrawal_date_is_open(withdrawn_on):
    if not withdrawn_on:
        raise ValidationError({'withdrawn_on': 'Select the withdrawal date.'})
    today = timezone.localdate()
    if withdrawn_on > today:
        raise ValidationError({'withdrawn_on': 'A withdrawal cannot be dated in the future.'})
    if withdrawn_on.year != active_saving_year(today):
        raise ValidationError({
            'withdrawn_on': 'Withdrawals can only be recorded in the current open saving year.'
        })
    if submissions_locked_for_year(withdrawn_on.year):
        raise ValidationError({
            'withdrawn_on': f'The {withdrawn_on.year} financial year is locked.'
        })


def account_balance(account, *, year=None, as_of=None, exclude_withdrawal_id=None):
    as_of = as_of or timezone.localdate()
    year = year or active_saving_year(as_of)
    gross = (
        DepositSubmission.objects.filter(
            account=account,
            status='APPROVED',
            payment_week__year=year,
        ).aggregate(total=Sum('saving_amount'))['total']
        or ZERO
    )
    withdrawals = Withdrawal.objects.filter(
        account=account,
        is_voided=False,
        withdrawn_on__year=year,
        withdrawn_on__lte=as_of,
    )
    if exclude_withdrawal_id:
        withdrawals = withdrawals.exclude(pk=exclude_withdrawal_id)
    withdrawn = withdrawals.aggregate(total=Sum('amount'))['total'] or ZERO
    net = max(gross - withdrawn, ZERO)

    own_loans = (
        LoanRequest.objects.filter(
            account=account,
            status=LoanRequest.STATUS_APPROVED,
            approved_on__date__lte=as_of,
        ).prefetch_related('repayments', 'year_end_snapshots')
    )
    borrower_hold = sum(
        (loan.outstanding_balance_as_of(as_of) for loan in own_loans), ZERO
    )

    guarantor_hold = ZERO
    approvals = (
        LoanGuarantorApproval.objects.filter(
            account=account,
            status=LoanGuarantorApproval.STATUS_APPROVED,
            loan__status=LoanRequest.STATUS_APPROVED,
            loan__approved_on__date__lte=as_of,
        )
        .select_related('loan')
        .prefetch_related('loan__repayments', 'loan__year_end_snapshots')
    )
    for approval in approvals:
        guarantor_count = LoanGuarantorApproval.objects.filter(
            loan=approval.loan,
            status=LoanGuarantorApproval.STATUS_APPROVED,
            account__isnull=False,
        ).count()
        if guarantor_count:
            guarantor_hold += approval.loan.outstanding_balance_as_of(as_of) / Decimal(guarantor_count)

    protected = borrower_hold + guarantor_hold
    return {
        'year': year,
        'gross': gross,
        'withdrawn': withdrawn,
        'net': net,
        'borrower_hold': borrower_hold,
        'guarantor_hold': guarantor_hold,
        'protected': protected,
        'withdrawable': max(net - protected, ZERO),
    }


def snapshot(withdrawal):
    return {
        'member': {'id': withdrawal.member_id, 'label': str(withdrawal.member)},
        'account': {'id': withdrawal.account_id, 'label': str(withdrawal.account)},
        'amount': str(withdrawal.amount),
        'withdrawn_on': withdrawal.withdrawn_on.isoformat(),
        'reason': withdrawal.reason,
        'reference': withdrawal.reference,
        'notes': withdrawal.notes,
        'is_voided': withdrawal.is_voided,
        'void_reason': withdrawal.void_reason,
    }


def _notify(withdrawal, action):
    balance = account_balance(withdrawal.account)
    send_notification(
        subject=f'Savings withdrawal {action}',
        body=(
            f'A savings withdrawal of UGX {withdrawal.amount:,.0f} for account '
            f'{withdrawal.account.label} was {action}. Date: {withdrawal.withdrawn_on:%d %B %Y}. '
            f'Reference: {withdrawal.reference or "Not provided"}. '
            f'Current net savings: UGX {balance["net"]:,.0f}.'
        ),
        recipients=[withdrawal.member],
        sender=None,
    )


def _validate_amount(account, amount, withdrawn_on, exclude_id=None):
    # Validate against today's complete ledger, not only entries that happened
    # before a backdated-in-year transaction. This prevents a correction from
    # making the account overdrawn when later withdrawals already exist.
    balance = account_balance(
        account,
        year=withdrawn_on.year,
        as_of=timezone.localdate(),
        exclude_withdrawal_id=exclude_id,
    )
    if amount > balance['withdrawable']:
        raise ValidationError({
            'amount': (
                f'Only UGX {balance["withdrawable"]:,.0f} is withdrawable after '
                'protecting loan and guarantor obligations.'
            )
        })
    return balance


@transaction.atomic
def create_withdrawal(*, data, user):
    if not user.is_treasurer():
        raise PermissionDenied('Only the Treasurer can record withdrawals.')
    account = SavingsAccount.objects.select_for_update().select_related('owner').get(
        pk=data['account'].pk
    )
    ensure_withdrawal_date_is_open(data['withdrawn_on'])
    _validate_amount(account, data['amount'], data['withdrawn_on'])
    withdrawal = Withdrawal(
        member=account.owner,
        account=account,
        amount=data['amount'],
        withdrawn_on=data['withdrawn_on'],
        reason=' '.join(data['reason'].split()),
        reference=(data.get('reference') or '').strip(),
        notes=(data.get('notes') or '').strip(),
        recorded_by=user,
    )
    withdrawal.full_clean()
    withdrawal.save()
    transaction.on_commit(lambda: _notify(withdrawal, 'recorded'))
    return withdrawal


@transaction.atomic
def edit_withdrawal(*, withdrawal_id, data, user, correction_reason):
    if not user.is_treasurer():
        raise PermissionDenied('Only the Treasurer can edit withdrawals.')
    withdrawal = Withdrawal.objects.select_for_update().select_related('account', 'member').get(
        pk=withdrawal_id
    )
    if withdrawal.is_voided:
        raise ValidationError('A voided withdrawal cannot be edited.')
    ensure_withdrawal_date_is_open(withdrawal.withdrawn_on)
    ensure_withdrawal_date_is_open(data['withdrawn_on'])
    reason = ' '.join((correction_reason or '').split())
    if len(reason) < 5:
        raise ValidationError({'correction_reason': 'Give a correction reason of at least 5 characters.'})

    account_ids = sorted({withdrawal.account_id, data['account'].pk})
    locked = {
        item.pk: item
        for item in SavingsAccount.objects.select_for_update().select_related('owner').filter(
            pk__in=account_ids
        )
    }
    new_account = locked[data['account'].pk]
    _validate_amount(
        new_account,
        data['amount'],
        data['withdrawn_on'],
        exclude_id=withdrawal.pk if new_account.pk == withdrawal.account_id else None,
    )
    before = snapshot(withdrawal)
    withdrawal.member = new_account.owner
    withdrawal.account = new_account
    withdrawal.amount = data['amount']
    withdrawal.withdrawn_on = data['withdrawn_on']
    withdrawal.reason = ' '.join(data['reason'].split())
    withdrawal.reference = (data.get('reference') or '').strip()
    withdrawal.notes = (data.get('notes') or '').strip()
    withdrawal.full_clean()
    withdrawal.save()
    latest = withdrawal.revisions.order_by('-revision_number').first()
    WithdrawalRevision.objects.create(
        withdrawal=withdrawal,
        revision_number=(latest.revision_number + 1) if latest else 1,
        before_data=before,
        after_data=snapshot(withdrawal),
        reason=reason,
        edited_by=user,
    )
    transaction.on_commit(lambda: _notify(withdrawal, 'corrected'))
    return withdrawal


@transaction.atomic
def void_withdrawal(*, withdrawal_id, user, reason):
    if not user.is_treasurer():
        raise PermissionDenied('Only the Treasurer can void withdrawals.')
    withdrawal = Withdrawal.objects.select_for_update().select_related('account', 'member').get(
        pk=withdrawal_id
    )
    SavingsAccount.objects.select_for_update().get(pk=withdrawal.account_id)
    if withdrawal.is_voided:
        raise ValidationError('This withdrawal is already voided.')
    ensure_withdrawal_date_is_open(withdrawal.withdrawn_on)
    reason = ' '.join((reason or '').split())
    if len(reason) < 5:
        raise ValidationError('Give a void reason of at least 5 characters.')
    before = snapshot(withdrawal)
    withdrawal.is_voided = True
    withdrawal.void_reason = reason
    withdrawal.voided_by = user
    withdrawal.voided_at = timezone.now()
    withdrawal.save(update_fields=['is_voided', 'void_reason', 'voided_by', 'voided_at', 'updated_at'])
    latest = withdrawal.revisions.order_by('-revision_number').first()
    WithdrawalRevision.objects.create(
        withdrawal=withdrawal,
        revision_number=(latest.revision_number + 1) if latest else 1,
        before_data=before,
        after_data=snapshot(withdrawal),
        reason=reason,
        edited_by=user,
    )
    transaction.on_commit(lambda: _notify(withdrawal, 'voided'))
    return withdrawal

