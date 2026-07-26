from datetime import datetime, time
from decimal import Decimal, ROUND_DOWN

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from deposits.models import DepositSubmission, DepositWelfareAllocation
from deposits.rules import saving_year_weeks
from fines.models import Fine
from groupcore.models import (
    AccountSettlement,
    FinancialYearClose,
    FinancialYearLoanSnapshot,
    GroupSettings,
    SavingsAccount,
    SettlementLoanAllocation,
    SettlementPayoutPayment,
    SettlementVersion,
)
from groupcore.savings_calendar import apply_year_end_fine_relief
from groupcore.week_cycle import first_friday_of_year, saving_year_closing_date
from incomes.models import AnnualSubscription
from loans.models import LoanGuarantorApproval, LoanRequest


ZERO = Decimal('0.00')
ANNUAL_SUBSCRIPTION = Decimal('10000.00')
WEEKLY_WELFARE = Decimal('1000.00')


def financial_year(year):
    state, _created = FinancialYearClose.objects.get_or_create(
        year=year,
        defaults={'scheduled_closing_date': saving_year_closing_date(year)},
    )
    return state


def pending_at_cutoff(state):
    if not state.cutoff_at:
        return DepositSubmission.objects.none()
    return DepositSubmission.objects.filter(
        payment_week__year=state.year,
        date_submitted__lte=state.cutoff_at,
        status='PENDING',
        member__is_superuser=False,
    )


def _snapshot_loans(state):
    cutoff_date = timezone.localtime(state.cutoff_at).date()
    loans = (
        LoanRequest.objects.select_for_update()
        .filter(
            status=LoanRequest.STATUS_APPROVED,
            approved_on__lte=state.cutoff_at,
            member__is_superuser=False,
        )
        .prefetch_related('repayments')
    )
    for loan in loans:
        balance = loan.outstanding_balance_as_of(cutoff_date)
        if balance <= 0:
            continue
        interest = (
            loan.repayments.filter(
                paid_on__year=state.year,
                paid_on__lte=cutoff_date,
                created_at__lte=state.cutoff_at,
            ).aggregate(total=Sum('interest_component'))['total']
            or ZERO
        )
        FinancialYearLoanSnapshot.objects.get_or_create(
            financial_year=state,
            loan=loan,
            defaults={
                'frozen_balance': balance,
                'collected_interest': interest,
                'frozen_at': state.cutoff_at,
            },
        )


@transaction.atomic
def lock_financial_year(year, user=None, *, automatic=False, cutoff_at=None):
    if not automatic and (not user or not user.is_treasurer()):
        raise PermissionDenied('Only the treasurer can close the financial year.')
    state = FinancialYearClose.objects.select_for_update().filter(year=year).first()
    if not state:
        state = FinancialYearClose.objects.create(
            year=year, scheduled_closing_date=saving_year_closing_date(year)
        )
        state = FinancialYearClose.objects.select_for_update().get(pk=state.pk)
    today = timezone.localdate(cutoff_at) if cutoff_at else timezone.localdate()
    if not automatic and today < state.scheduled_closing_date:
        raise ValidationError(
            f'The {year} financial year cannot close before '
            f'{state.scheduled_closing_date:%d %B %Y}.'
        )
    if state.state != FinancialYearClose.STATE_OPEN:
        return state
    state.cutoff_at = cutoff_at or timezone.now()
    state.state = FinancialYearClose.STATE_LOCKED
    state.locked_by = None if automatic else user
    state.auto_locked = automatic
    state.save(update_fields=[
        'cutoff_at', 'state', 'locked_by', 'auto_locked', 'updated_at',
    ])
    _snapshot_loans(state)
    apply_year_end_fine_relief(year=year, as_of=max(today, state.scheduled_closing_date))
    return state


def ensure_automatic_year_lock(today=None):
    today = today or timezone.localdate()
    previous_year = today.year - 1
    if today < first_friday_of_year(today.year):
        return financial_year(previous_year)
    state = financial_year(previous_year)
    if state.state == FinancialYearClose.STATE_OPEN:
        tz = timezone.get_current_timezone()
        cutoff = timezone.make_aware(
            datetime.combine(first_friday_of_year(today.year), time.min), tz
        )
        state = lock_financial_year(
            previous_year, automatic=True, cutoff_at=cutoff
        )
    return state


def submissions_locked_for_year(year):
    ensure_automatic_year_lock()
    return financial_year(year).state != FinancialYearClose.STATE_OPEN


def loan_activity_frozen(loan=None, today=None):
    today = today or timezone.localdate()
    ensure_automatic_year_lock(today)
    locked = FinancialYearClose.objects.filter(
        state=FinancialYearClose.STATE_LOCKED
    )
    for state in locked:
        if loan is not None and state.loan_snapshots.filter(loan=loan).exists():
            return True
        if today < first_friday_of_year(state.year + 1):
            return True
    return False


def apply_eligible_locked_repayment(repayment):
    """Apply an eligible pre-cutoff deposit repayment to its frozen loan snapshot."""
    if not repayment.source_deposit_id:
        return False
    snapshot = (
        FinancialYearLoanSnapshot.objects.select_for_update()
        .select_related('financial_year', 'loan')
        .filter(
            loan=repayment.loan,
            financial_year__state=FinancialYearClose.STATE_LOCKED,
        )
        .first()
    )
    if not snapshot:
        return False
    deposit = repayment.source_deposit
    if deposit.date_submitted > snapshot.financial_year.cutoff_at:
        raise ValidationError(
            'This repayment was submitted after the financial-year cutoff.'
        )
    snapshot.frozen_balance = max(
        snapshot.frozen_balance - repayment.amount, ZERO
    )
    snapshot.collected_interest += repayment.interest_component
    snapshot.save(update_fields=['frozen_balance', 'collected_interest'])
    return True


def _eligible_deposits(state):
    return DepositSubmission.objects.filter(
        payment_week__year=state.year,
        date_submitted__lte=state.cutoff_at,
        status='APPROVED',
        member__is_superuser=False,
    )


def _deduct_from_accounts(
    settlements, amount, allocation_field, version, snapshot, allocation_type,
    member, note, preferred_account_id=None,
):
    remaining = amount
    candidates = [item for item in settlements if item.member_id == member.id]
    candidates.sort(
        key=lambda item: (
            0 if preferred_account_id and item.account_id == preferred_account_id else 1,
            -item.net_payout,
            item.account_id,
        )
    )
    for item in candidates:
        available = max(item.net_payout, ZERO)
        used = min(available, remaining)
        if used <= 0:
            continue
        item.net_payout -= used
        setattr(item, allocation_field, getattr(item, allocation_field) + used)
        SettlementLoanAllocation.objects.create(
            settlement_version=version,
            loan_snapshot=snapshot,
            allocation_type=allocation_type,
            member=member,
            account=item.account,
            amount=used,
            note=note,
        )
        remaining -= used
        if remaining <= 0:
            break
    return remaining


@transaction.atomic
def finalize_financial_year(year, user):
    if not user.is_treasurer():
        raise PermissionDenied('Only the treasurer can finalize a settlement.')
    state = FinancialYearClose.objects.select_for_update().get(year=year)
    if state.state == FinancialYearClose.STATE_OPEN:
        raise ValidationError('Lock the financial year before finalizing it.')
    if pending_at_cutoff(state).exists():
        raise ValidationError('Approve or reject every eligible pending deposit first.')
    if (
        state.state == FinancialYearClose.STATE_FINALIZED
        and not state.needs_regeneration
    ):
        return state.versions.get(version=state.current_version)

    version_number = state.current_version + 1
    previous = state.versions.filter(version=state.current_version).first()
    version = SettlementVersion.objects.create(
        financial_year=state,
        version=version_number,
        created_by=user,
        cutoff_at=state.cutoff_at,
    )
    deposits = _eligible_deposits(state)
    settings = GroupSettings.get_active()
    _active, weeks = saving_year_weeks(
        settings.week_one_start,
        state.scheduled_closing_date,
    ) if settings else (None, [])
    accounts = list(
        SavingsAccount.objects.filter(owner__is_superuser=False)
        .select_related('owner')
    )
    savings_rows = {
        row['account_id']: row['total'] or ZERO
        for row in deposits.filter(account__isnull=False)
        .values('account_id').annotate(total=Sum('saving_amount'))
    }
    total_savings = sum(savings_rows.values(), ZERO)
    interest_pool = (
        state.loan_snapshots.aggregate(total=Sum('collected_interest'))['total']
        or ZERO
    )
    prior_paid = {}
    if previous:
        prior_paid = {
            row.account_id: row.amount_paid
            for row in previous.account_settlements.all()
        }

    settlements = []
    for account in accounts:
        savings = savings_rows.get(account.id, ZERO)
        interest_share = (
            (interest_pool * savings / total_savings) if total_savings else ZERO
        )
        welfare_paid = (
            DepositWelfareAllocation.objects.filter(
                account=account,
                welfare_week__in=weeks,
                deposit__in=deposits,
            ).aggregate(total=Sum('amount'))['total']
            or ZERO
        )
        welfare_due = max(WEEKLY_WELFARE * len(weeks) - welfare_paid, ZERO)
        fine_due = sum(
            (
                fine.outstanding_amount
                for fine in Fine.objects.filter(
                    member=account.owner,
                    account=account,
                    is_voided=False,
                ).filter(
                    Q(reference_week__year=year)
                    | Q(reference_week__isnull=True, date_issued__year=year)
                )
            ),
            ZERO,
        )
        gross = savings + interest_share
        net = max(gross - welfare_due - fine_due, ZERO)
        settlements.append(AccountSettlement.objects.create(
            settlement_version=version,
            account=account,
            member=account.owner,
            savings_total=savings,
            interest_share=interest_share,
            welfare_due=welfare_due,
            fine_due=fine_due,
            gross_payout=gross,
            net_payout=net,
            amount_paid=prior_paid.get(account.id, ZERO),
        ))

    # Older and member-wide fines without an account are charged to the
    # member's largest available payout, without duplicating account fines.
    for member_id in {item.member_id for item in settlements}:
        unassigned_fine_due = sum(
            (
                fine.outstanding_amount
                for fine in Fine.objects.filter(
                    member_id=member_id,
                    account__isnull=True,
                    is_voided=False,
                ).filter(
                    Q(reference_week__year=year)
                    | Q(reference_week__isnull=True, date_issued__year=year)
                )
            ),
            ZERO,
        )
        for item in sorted(
            [row for row in settlements if row.member_id == member_id],
            key=lambda row: (-row.net_payout, row.account_id),
        ):
            used = min(item.net_payout, unassigned_fine_due)
            item.net_payout -= used
            item.fine_due += used
            unassigned_fine_due -= used
            if unassigned_fine_due <= 0:
                break

    # Member-level annual subscriptions are charged to the largest payout first.
    members = {item.member_id: item.member for item in settlements}
    annual_paid_rows = {
        row['member_id']: row['total'] or ZERO
        for row in deposits.values('member_id').annotate(
            total=Sum('annual_subscription_amount')
        )
    }
    for member_id, member in members.items():
        subscription = AnnualSubscription.objects.filter(
            member_id=member_id, year=year, is_paid=True
        ).first()
        annual_paid = ANNUAL_SUBSCRIPTION if subscription else annual_paid_rows.get(member_id, ZERO)
        due = max(ANNUAL_SUBSCRIPTION - annual_paid, ZERO)
        for item in sorted(
            [row for row in settlements if row.member_id == member_id],
            key=lambda row: (-row.net_payout, row.account_id),
        ):
            used = min(item.net_payout, due)
            item.net_payout -= used
            item.annual_due += used
            due -= used
            if due <= 0:
                break

    group_loss = ZERO
    snapshots = state.loan_snapshots.select_related(
        'loan', 'loan__member', 'loan__account'
    ).prefetch_related('loan__guarantor_approvals__guarantor').order_by(
        'loan__approved_on', 'loan_id'
    )
    for snapshot in snapshots:
        loan = snapshot.loan
        remaining = _deduct_from_accounts(
            settlements, snapshot.frozen_balance, 'borrower_loan_offset',
            version, snapshot, SettlementLoanAllocation.TYPE_BORROWER,
            loan.member, 'Borrower year-end loan offset.', loan.account_id,
        )
        guarantors = [
            approval.guarantor
            for approval in loan.guarantor_approvals.all()
            if approval.status == LoanGuarantorApproval.STATUS_APPROVED
        ]
        if remaining > 0 and guarantors:
            base_share = (remaining / len(guarantors)).quantize(
                Decimal('0.01'), rounding=ROUND_DOWN
            )
            assigned = ZERO
            for index, guarantor in enumerate(guarantors):
                share = remaining - assigned if index == len(guarantors) - 1 else base_share
                assigned += share
                shortfall = _deduct_from_accounts(
                    settlements, share, 'guarantor_offset',
                    version, snapshot, SettlementLoanAllocation.TYPE_GUARANTOR,
                    guarantor, f'Equal guarantor share for Loan #{loan.id}.',
                )
                if shortfall > 0:
                    SettlementLoanAllocation.objects.create(
                        settlement_version=version,
                        loan_snapshot=snapshot,
                        allocation_type=SettlementLoanAllocation.TYPE_GROUP_LOSS,
                        member=guarantor,
                        amount=shortfall,
                        note='Uncovered guarantor share absorbed by the group.',
                    )
                    group_loss += shortfall
        elif remaining > 0:
            SettlementLoanAllocation.objects.create(
                settlement_version=version,
                loan_snapshot=snapshot,
                allocation_type=SettlementLoanAllocation.TYPE_GROUP_LOSS,
                member=loan.member,
                amount=remaining,
                note='Legacy loan without qualifying guarantors; absorbed by the group.',
            )
            group_loss += remaining
        loan.status = LoanRequest.STATUS_SETTLED
        loan.settlement_closed_on = timezone.now()
        loan.settlement_loss = sum(
            (
                allocation.amount
                for allocation in version.loan_allocations.filter(
                    loan_snapshot=snapshot,
                    allocation_type=SettlementLoanAllocation.TYPE_GROUP_LOSS,
                )
            ),
            ZERO,
        )
        loan.save(update_fields=['status', 'settlement_closed_on', 'settlement_loss'])

    for item in settlements:
        if item.amount_paid >= item.net_payout:
            item.payout_status = AccountSettlement.STATUS_PAID
        elif item.amount_paid > 0:
            item.payout_status = AccountSettlement.STATUS_PARTIAL
        item.save(update_fields=[
            'annual_due', 'borrower_loan_offset', 'guarantor_offset',
            'net_payout', 'amount_paid', 'payout_status',
        ])
    version.total_savings = total_savings
    version.collected_interest_pool = interest_pool
    version.total_payout = sum((item.net_payout for item in settlements), ZERO)
    version.total_group_loss = group_loss
    version.save(update_fields=[
        'total_savings', 'collected_interest_pool', 'total_payout',
        'total_group_loss',
    ])
    state.state = FinancialYearClose.STATE_FINALIZED
    state.finalized_at = timezone.now()
    state.finalized_by = user
    state.current_version = version_number
    state.needs_regeneration = False
    state.save(update_fields=[
        'state', 'finalized_at', 'finalized_by', 'current_version',
        'needs_regeneration', 'updated_at',
    ])
    return version


@transaction.atomic
def record_payout(account_settlement, amount, paid_on, reference, notes, user):
    if not user.is_treasurer():
        raise PermissionDenied('Only the treasurer can record settlement payouts.')
    item = AccountSettlement.objects.select_for_update().get(pk=account_settlement.pk)
    amount = Decimal(amount)
    if amount <= 0 or amount > item.outstanding_payout:
        raise ValidationError('Payout must be positive and cannot exceed the outstanding amount.')
    payment = SettlementPayoutPayment.objects.create(
        account_settlement=item,
        amount=amount,
        paid_on=paid_on,
        reference=reference,
        notes=notes,
        recorded_by=user,
    )
    item.amount_paid += amount
    item.payout_status = (
        AccountSettlement.STATUS_PAID
        if item.amount_paid >= item.net_payout
        else AccountSettlement.STATUS_PARTIAL
    )
    item.save(update_fields=['amount_paid', 'payout_status'])
    return payment
