from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from Assets_Expenditures.models import Asset, Expenditure
from deposits.models import DepositSubmission, DepositWelfareAllocation
from deposits.rules import saving_year_weeks
from deposits.welfare_calendar import WEEKLY_WELFARE_AMOUNT
from fines.models import Fine
from groupcore.models import FinancialRecordRevision, GroupSettings, SavingsAccount
from groupcore.member_query import alphabetical_members
from incomes.models import AnnualSubscription, OtherIncome, ShareContribution
from loans.models import LoanRepayment, LoanRequest


RECORD_MODELS = {
    'deposit': DepositSubmission,
    'fine': Fine,
    'loan': LoanRequest,
    'repayment': LoanRepayment,
    'share': ShareContribution,
    'subscription': AnnualSubscription,
    'income': OtherIncome,
    'asset': Asset,
    'expenditure': Expenditure,
}

EDIT_FIELDS = {
    'deposit': [
        'member', 'account', 'payment_week', 'payment_date', 'payment_time',
        'saving_amount', 'annual_subscription_amount', 'membership_amount',
        'shares_amount', 'loan_repayment_loan', 'loan_repayment_amount',
        'proof', 'remarks',
    ],
    'fine': [
        'member', 'account', 'fine_type', 'reference_week', 'reason', 'amount',
        'amount_paid', 'remarks',
    ],
    'loan': [
        'member', 'account', 'principal', 'monthly_interest_rate',
        'duration_months', 'purpose', 'remarks',
    ],
    'repayment': ['loan', 'amount', 'paid_on', 'notes'],
    'share': ['member', 'account', 'amount', 'remarks'],
    'subscription': ['member', 'year', 'amount', 'is_paid', 'paid_on'],
    'income': ['source', 'fine', 'amount', 'description'],
    'asset': ['name', 'value', 'date_acquired', 'source', 'remarks'],
    'expenditure': ['description', 'amount', 'date_spent', 'source', 'remarks'],
}

AUDIT_FIELD_LABELS = {
    'member': 'Member',
    'account': 'Savings account',
    'starting_week': 'Starting week',
    'weeks_covered': 'Weeks covered',
    'payment_week': 'Saving week',
    'saving_amount': 'Savings amount',
    'welfare_amount': 'Welfare amount',
    'annual_subscription_amount': 'Annual subscription',
    'membership_amount': 'Membership amount',
    'fine_amount': 'Fine payment',
    'shares_amount': 'Shares amount',
    'loan_repayment_amount': 'Loan repayment',
    'loan_repayment_loan': 'Selected loan',
    'amount': 'Total amount',
    'principal': 'Loan principal',
    'monthly_interest_rate': 'Monthly interest rate',
    'duration_months': 'Loan duration (months)',
    'purpose': 'Purpose',
    'proof': 'Payment proof',
    'remarks': 'Remarks',
    'payment_date': 'Payment date',
    'payment_time': 'Payment time',
    'status': 'Status',
    'submitted_by': 'Submitted by',
    'reviewed_by': 'Reviewed by',
    'date_submitted': 'Date submitted',
    'date_reviewed': 'Date reviewed',
    'record_state': 'Record status',
    'welfare_weeks': 'Welfare weeks',
    'fine_allocations': 'Fine allocations',
    'reason': 'Reason',
    'fine_type': 'Fine type',
    'reference_week': 'Fine week',
    'amount_paid': 'Amount paid',
    'is_paid': 'Paid',
    'paid_on': 'Payment date',
    'notes': 'Notes',
    'name': 'Name',
    'value': 'Value',
    'date_acquired': 'Date acquired',
    'date_spent': 'Date spent',
    'source': 'Fund source',
    'description': 'Description',
    'year': 'Year',
}

AUDIT_MONEY_FIELDS = {
    'saving_amount', 'welfare_amount', 'annual_subscription_amount',
    'membership_amount', 'fine_amount', 'shares_amount',
    'loan_repayment_amount', 'amount', 'principal', 'amount_paid', 'value',
}


def _friendly_audit_value(field_name, value):
    if isinstance(value, dict) and 'label' in value:
        return value.get('label') or (
            f"Record #{value.get('id')}" if value.get('id') else 'Not set'
        )
    if isinstance(value, list):
        if not value:
            return 'None'
        if field_name == 'welfare_weeks':
            return ', '.join(item.get('week', '') for item in value) or 'None'
        if field_name == 'fine_allocations':
            return ', '.join(
                f"Fine #{item.get('fine_id')} — UGX {Decimal(item.get('amount', '0')):,.0f}"
                for item in value
            )
        return ', '.join(str(item) for item in value)
    if value in (None, ''):
        return 'Not set'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if field_name in AUDIT_MONEY_FIELDS:
        try:
            return f'UGX {Decimal(str(value)):,.0f}'
        except Exception:
            pass
    return str(value)


def revision_changes(revision):
    """Return only user-meaningful changed fields in a display-ready form."""
    before = revision.before_data or {}
    after = revision.after_data or {}
    changes = []
    for field_name in sorted(set(before) | set(after)):
        old_value = before.get(field_name)
        new_value = after.get(field_name)
        if old_value == new_value:
            continue
        changes.append({
            'field': field_name,
            'label': AUDIT_FIELD_LABELS.get(
                field_name,
                field_name.replace('_', ' ').title(),
            ),
            'before': _friendly_audit_value(field_name, old_value),
            'after': _friendly_audit_value(field_name, new_value),
        })
    return changes


def record_owner(record):
    if hasattr(record, 'member_id'):
        return record.member
    if isinstance(record, LoanRepayment):
        return record.loan.member
    return None


def is_financial_manager(user):
    return user.is_authenticated and user.role in {
        'TREASURER', 'CHAIRMAN', 'VICE_CHAIRMAN', 'SECRETARY', 'OVERSEER',
    }


def can_inspect_record(user, record):
    owner = record_owner(record)
    return is_financial_manager(user) or bool(owner and owner.pk == user.pk)


def snapshot_record(record):
    data = {}
    for field in record._meta.concrete_fields:
        if field.primary_key:
            continue
        value = field.value_from_object(record)
        key = field.name
        if field.is_relation:
            data[key] = {
                'id': value,
                'label': str(getattr(record, field.name, '') or ''),
            }
        elif isinstance(value, (Decimal, date, datetime, time, UUID)):
            data[key] = value.isoformat() if hasattr(value, 'isoformat') else str(value)
        elif hasattr(value, 'name'):
            data[key] = value.name
        else:
            data[key] = value
    if isinstance(record, DepositSubmission) and record.pk:
        data['welfare_weeks'] = [
            {'week': item.welfare_week.isoformat(), 'amount': str(item.amount)}
            for item in record.welfare_allocations.all()
        ]
        data['fine_allocations'] = [
            {'fine_id': item.fine_id, 'amount': str(item.amount)}
            for item in record.fine_allocations.all()
        ]
    return data


def record_revision(record, before_data, editor, reason):
    record_type = next(key for key, model in RECORD_MODELS.items() if isinstance(record, model))
    latest = (
        FinancialRecordRevision.objects.select_for_update()
        .filter(record_type=record_type, object_id=record.pk)
        .order_by('-revision_number')
        .first()
    )
    return FinancialRecordRevision.objects.create(
        record_type=record_type,
        object_id=record.pk,
        revision_number=(latest.revision_number + 1) if latest else 1,
        before_data=before_data,
        after_data=snapshot_record(record),
        reason=reason,
        edited_by=editor,
    )


class FinancialRecordEditForm(forms.ModelForm):
    edit_reason = forms.CharField(
        label='Reason for correction',
        min_length=5,
        widget=forms.Textarea(attrs={'rows': 3}),
    )

    def __init__(self, *args, record_type, **kwargs):
        self.record_type = record_type
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.DateInput):
                field.widget.attrs['type'] = 'date'
            if isinstance(field.widget, forms.TimeInput):
                field.widget.attrs['type'] = 'time'
            field.widget.attrs.setdefault(
                'class',
                'form-select' if isinstance(field, forms.ModelChoiceField) else 'form-control',
            )
        if 'member' in self.fields:
            self.fields['member'].queryset = alphabetical_members(
                self.fields['member'].queryset.filter(is_superuser=False)
            )
        if 'account' in self.fields:
            member_id = (
                self.data.get('member') if self.is_bound
                else getattr(self.instance, 'member_id', None)
            )
            self.fields['account'].queryset = SavingsAccount.objects.filter(
                owner_id=member_id, is_active=True
            ).order_by('label')
        if record_type == 'deposit':
            deposit_member_id = self.data.get('member') if self.is_bound else getattr(self.instance, 'member_id', None)
            deposit_account_id = self.data.get('account') if self.is_bound else getattr(self.instance, 'account_id', None)
            self.fields['loan_repayment_loan'].queryset = LoanRequest.objects.filter(
                member_id=deposit_member_id,
                account_id=deposit_account_id,
                status='APPROVED',
            ).order_by('approved_on', 'id')
            settings = GroupSettings.get_active()
            available_weeks = []
            if settings:
                _active, available_weeks = saving_year_weeks(settings.week_one_start)
            existing_weeks = list(
                self.instance.welfare_allocations.values_list('welfare_week', flat=True)
            ) if self.instance.pk else []
            occupied_weeks = set()
            if deposit_account_id:
                occupied = DepositWelfareAllocation.objects.filter(
                    account_id=deposit_account_id,
                    deposit__status__in=('PENDING', 'APPROVED'),
                )
                if self.instance.pk:
                    occupied = occupied.exclude(deposit=self.instance)
                occupied_weeks = set(
                    occupied.values_list('welfare_week', flat=True)
                )
            # A week covered by another pending/approved deposit is not offered.
            # Existing weeks remain selectable so the treasurer can remove or
            # retain this deposit's own allocations during a correction.
            welfare_weeks = sorted(
                (set(available_weeks) - occupied_weeks) | set(existing_weeks)
            )
            existing_week_set = set(existing_weeks)
            self.fields['welfare_weeks'] = forms.MultipleChoiceField(
                choices=[
                    (
                        week.isoformat(),
                        (
                            f'{week:%d %B %Y} — currently on this deposit'
                            if week in existing_week_set
                            else f'{week:%d %B %Y}'
                        ),
                    )
                    for week in welfare_weeks
                ],
                required=False,
                widget=forms.CheckboxSelectMultiple,
                initial=[week.isoformat() for week in existing_weeks],
                label='Welfare weeks (UGX 1,000 each)',
            )
            member_id = deposit_member_id or getattr(self.instance, 'member_id', None)
            account_id = deposit_account_id or getattr(self.instance, 'account_id', None)
            fine_qs = Fine.objects.filter(member_id=member_id)
            if account_id:
                fine_qs = fine_qs.filter(account_id=account_id)
            existing_fine_ids = list(
                self.instance.fine_allocations.values_list('fine_id', flat=True)
            ) if self.instance.pk else []
            self.fields['selected_fines'] = forms.ModelMultipleChoiceField(
                queryset=fine_qs.filter(
                    models.Q(is_paid=False, is_voided=False) | models.Q(pk__in=existing_fine_ids)
                ).order_by('reference_week', 'id'),
                required=False,
                widget=forms.CheckboxSelectMultiple,
                initial=existing_fine_ids,
                label='Fine weeks paid by this deposit',
            )

    class Meta:
        model = DepositSubmission
        fields = EDIT_FIELDS['deposit']

    def clean(self):
        cleaned = super().clean()
        instance = self.instance
        member = cleaned.get('member')
        account = cleaned.get('account')
        if member and account and account.owner_id != member.id:
            self.add_error('account', 'Selected account does not belong to this member.')

        if self.record_type == 'deposit':
            if instance.pk and instance.status == 'APPROVED':
                fine_total = sum(
                    (item.amount for item in instance.fine_allocations.all()),
                    Decimal('0.00'),
                )
                if fine_total and instance.fine_amount != fine_total:
                    raise ValidationError('Existing fine allocations are inconsistent; inspect them before editing.')
                welfare_total = sum(
                    (item.amount for item in instance.welfare_allocations.all()),
                    Decimal('0.00'),
                )
                if welfare_total and instance.welfare_amount != welfare_total:
                    raise ValidationError('Existing welfare allocations are inconsistent; inspect them before editing.')
                identity_changed = (
                    getattr(member, 'id', None) != instance.member_id
                    or getattr(account, 'id', None) != instance.account_id
                )
                if identity_changed and instance.fine_allocations.exists():
                    raise ValidationError(
                        'A deposit with applied fines cannot be moved to another member/account. '
                        'Correct the fine record separately.'
                    )
                if identity_changed and instance.welfare_allocations.exists():
                    if not account:
                        raise ValidationError('A deposit with welfare weeks must keep an account.')
                    clashes = DepositWelfareAllocation.objects.filter(
                        account=account,
                        welfare_week__in=instance.welfare_allocations.values('welfare_week'),
                        deposit__status__in=('PENDING', 'APPROVED'),
                    ).exclude(deposit=instance)
                    if clashes.exists():
                        raise ValidationError('The destination account already has one of these welfare weeks.')
            welfare_dates = []
            for value in cleaned.get('welfare_weeks') or []:
                try:
                    welfare_dates.append(date.fromisoformat(value))
                except ValueError:
                    self.add_error('welfare_weeks', 'Select valid welfare weeks.')
            if welfare_dates and not account:
                self.add_error('account', 'Select an account for welfare weeks.')
            elif account:
                occupied = DepositWelfareAllocation.objects.filter(
                    account=account,
                    welfare_week__in=welfare_dates,
                    deposit__status__in=('PENDING', 'APPROVED'),
                )
                if instance.pk:
                    occupied = occupied.exclude(deposit=instance)
                if occupied.exists():
                    self.add_error('welfare_weeks', 'One or more welfare weeks are already paid or pending.')
            self.welfare_dates = welfare_dates

            old_fine_amounts = {
                item.fine_id: item.amount for item in instance.fine_allocations.all()
            } if instance.pk and instance.status == 'APPROVED' else {}
            self.fine_targets = []
            for fine in cleaned.get('selected_fines') or []:
                if fine.is_voided:
                    self.add_error('selected_fines', 'A voided fine cannot be selected for payment.')
                    continue
                target = fine.outstanding_amount + old_fine_amounts.get(fine.id, Decimal('0.00'))
                if target > 0:
                    self.fine_targets.append((fine.id, target))
            loan = cleaned.get('loan_repayment_loan')
            amount = cleaned.get('loan_repayment_amount') or Decimal('0.00')
            if amount > 0:
                if not loan or loan.member_id != getattr(member, 'id', None) or loan.account_id != getattr(account, 'id', None):
                    self.add_error('loan_repayment_loan', 'Select an approved loan for this member and account.')
                else:
                    existing = sum(
                        (item.amount for item in instance.generated_loan_repayments.all()),
                        Decimal('0.00'),
                    ) if instance.pk else Decimal('0.00')
                    balance = loan.outstanding_balance_as_of(cleaned.get('payment_date')) + existing
                    if amount > balance:
                        self.add_error('loan_repayment_amount', 'Repayment cannot exceed the loan balance.')
            elif loan:
                cleaned['loan_repayment_loan'] = None

        if self.record_type == 'fine':
            amount = cleaned.get('amount') or Decimal('0.00')
            amount_paid = cleaned.get('amount_paid') or Decimal('0.00')
            if amount_paid > amount:
                self.add_error('amount_paid', 'Paid amount cannot exceed the fine amount.')

        if self.record_type == 'repayment' and instance.pk and instance.source_deposit_id:
            raise ValidationError('This repayment came from a deposit. Edit the source deposit instead.')
        return cleaned


def financial_record_form_class(record_type):
    meta = type('Meta', (), {
        'model': RECORD_MODELS[record_type],
        'fields': EDIT_FIELDS[record_type],
    })
    return type(
        f'{record_type.title()}FinancialRecordEditForm',
        (FinancialRecordEditForm,),
        {'Meta': meta},
    )


def save_financial_edit(form, editor):
    record = form.instance
    original = type(record).objects.get(pk=record.pk)
    before = snapshot_record(original)
    reason = form.cleaned_data['edit_reason'].strip()
    with transaction.atomic():
        if isinstance(record, DepositSubmission) and record.status == 'APPROVED':
            for allocation in record.fine_allocations.select_related('fine'):
                fine = Fine.objects.select_for_update().get(pk=allocation.fine_id)
                fine.amount_paid = max(fine.amount_paid - allocation.amount, Decimal('0.00'))
                fine.is_paid = fine.amount_paid >= fine.amount
                fine.save(update_fields=['amount_paid', 'is_paid'])
            record.generated_loan_repayments.all().delete()
        if isinstance(record, DepositSubmission):
            record.fine_allocations.all().delete()
            record.welfare_allocations.all().delete()

        record = form.save(commit=False)
        if isinstance(record, DepositSubmission):
            welfare_dates = getattr(form, 'welfare_dates', [])
            fine_targets = getattr(form, 'fine_targets', [])
            record.welfare_amount = WEEKLY_WELFARE_AMOUNT * len(welfare_dates)
            record.fine_amount = sum((amount for _fine_id, amount in fine_targets), Decimal('0.00'))
        if isinstance(record, Fine):
            record.is_paid = record.amount_paid >= record.amount
        record.full_clean()
        record.save()

        if isinstance(record, DepositSubmission):
            for welfare_week in getattr(form, 'welfare_dates', []):
                DepositWelfareAllocation.objects.create(
                    deposit=record, account=record.account, welfare_week=welfare_week,
                )
            from deposits.models import DepositFineAllocation
            for fine_id, amount in getattr(form, 'fine_targets', []):
                fine = Fine.objects.select_for_update().get(pk=fine_id)
                if fine.is_voided:
                    raise ValidationError('A selected fine was voided before this correction was saved.')
                if amount > fine.outstanding_amount:
                    raise ValidationError('A selected fine no longer has enough outstanding balance.')
                DepositFineAllocation.objects.create(deposit=record, fine=fine, amount=amount)
                if record.status == 'APPROVED':
                    fine.apply_payment(amount)
            if record.status == 'APPROVED' and record.loan_repayment_amount > 0:
                loan = LoanRequest.objects.select_for_update().get(
                    pk=record.loan_repayment_loan_id, status='APPROVED'
                )
                balance = loan.outstanding_balance_as_of(record.payment_date)
                if record.loan_repayment_amount > balance:
                    raise ValidationError('Repayment exceeds the selected loan balance.')
                repayment = LoanRepayment(
                    loan=loan,
                    source_deposit=record,
                    amount=record.loan_repayment_amount,
                    paid_on=record.payment_date,
                    recorded_by=editor,
                    notes=f'Corrected deposit repayment (Deposit #{record.id}).',
                )
                repayment.full_clean()
                repayment.save()
        record_revision(record, before, editor, reason)
        settlement_year = None
        if isinstance(record, DepositSubmission) and record.payment_week:
            settlement_year = record.payment_week.year
        elif isinstance(record, Fine):
            settlement_year = (
                record.reference_week.year if record.reference_week
                else record.date_issued.year
            )
        elif isinstance(record, LoanRequest):
            settlement_year = (
                record.approved_on.year if record.approved_on
                else record.requested_on.year
            )
        elif isinstance(record, LoanRepayment):
            settlement_year = record.paid_on.year
        elif isinstance(record, ShareContribution):
            settlement_year = record.contribution_date.year
        elif isinstance(record, AnnualSubscription):
            settlement_year = record.year
        if settlement_year:
            from groupcore.models import FinancialYearClose
            FinancialYearClose.objects.filter(
                year=settlement_year,
                state=FinancialYearClose.STATE_FINALIZED,
            ).update(
                needs_regeneration=True,
                last_correction_at=timezone.now(),
            )
    return record


def delete_deposit_with_audit(deposit_id, editor, reason):
    """Delete a deposit while retaining a complete independent audit snapshot."""
    reason = (reason or '').strip()
    if len(reason) < 5:
        raise ValidationError('Give a clear deletion reason of at least 5 characters.')

    with transaction.atomic():
        record = (
            DepositSubmission.objects.select_for_update()
            .select_related('member', 'account')
            .get(pk=deposit_id)
        )
        before = snapshot_record(record)
        if record.status == 'APPROVED':
            allocations = list(
                record.fine_allocations.select_related('fine').all()
            )
            if record.fine_amount > 0 and not allocations:
                raise ValidationError(
                    'This legacy fine payment is not linked to a specific fine. '
                    'Edit the record and select its fine before deleting it.'
                )
            for allocation in allocations:
                fine = Fine.objects.select_for_update().get(pk=allocation.fine_id)
                fine.amount_paid = max(
                    fine.amount_paid - allocation.amount,
                    Decimal('0.00'),
                )
                fine.is_paid = fine.amount_paid >= fine.amount
                fine.save(update_fields=['amount_paid', 'is_paid'])
            # Generated repayments are internal effects of this deposit. Their
            # removal makes the selected loan's live balance increase again.
            record.generated_loan_repayments.all().delete()

        settlement_year = record.payment_week.year if record.payment_week else None
        member = record.member
        account = record.account
        saving_amount = record.saving_amount
        record_id = record.pk
        latest = (
            FinancialRecordRevision.objects.select_for_update()
            .filter(record_type='deposit', object_id=record_id)
            .order_by('-revision_number')
            .first()
        )
        audit_before = dict(before)
        audit_before['record_state'] = 'Active'
        audit_after = dict(before)
        audit_after['record_state'] = 'Deleted'
        FinancialRecordRevision.objects.create(
            record_type='deposit',
            object_id=record_id,
            revision_number=(latest.revision_number + 1) if latest else 1,
            before_data=audit_before,
            after_data=audit_after,
            reason=reason,
            edited_by=editor,
        )
        record.delete()

        if settlement_year:
            from groupcore.models import FinancialYearClose
            FinancialYearClose.objects.filter(
                year=settlement_year,
                state=FinancialYearClose.STATE_FINALIZED,
            ).update(
                needs_regeneration=True,
                last_correction_at=timezone.now(),
            )

        # Once the saving credit is removed, an elapsed unpaid week must again
        # be considered by the normal idempotent missed-week fine processor.
        if saving_amount > 0 and account:
            from groupcore.savings_calendar import ensure_overdue_fines
            ensure_overdue_fines(
                member=member,
                account=account,
                now=timezone.now(),
            )
    return record_id
