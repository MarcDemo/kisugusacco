from django import forms
from .models import DepositSubmission
import datetime
from groupcore.models import GroupSettings, MemberProfile, SavingsAccount
from groupcore.week_cycle import current_saving_week
from loans.models import LoanRequest
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.db.models import Sum
from deposits.rules import MAX_WEEKLY_SAVINGS, MIN_WEEKLY_SAVINGS, weekly_savings_total


PURPOSE_CHOICES = [
    ('saving', 'Saving'),
    ('welfare', 'Welfare'),
    ('annual_subscription', 'Annual Subscription'),
    ('membership', 'Membership'),
    ('fine', 'Fine'),
    ('shares', 'Shares'),
    ('loan_repayment', 'Loan Repayment'),
]

PURPOSE_AMOUNT_FIELDS = {
    'saving': 'saving_amount',
    'welfare': 'welfare_amount',
    'annual_subscription': 'annual_subscription_amount',
    'membership': 'membership_amount',
    'fine': 'fine_amount',
    'shares': 'shares_amount',
    'loan_repayment': 'loan_repayment_amount',
}


class DepositSubmissionForm(forms.ModelForm):
    payment_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    payment_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))
    account = forms.ModelChoiceField(queryset=SavingsAccount.objects.none(), required=True, empty_label="-- Select Account --")
    proof = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        error_messages={
            'invalid_image': 'Upload proof of payment as an image. PDF files are not accepted; use JPG, JPEG, PNG, or another image file.',
        },
    )
    selected_purposes = forms.MultipleChoiceField(
        choices=PURPOSE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Deposit Purpose",
    )
    saving_amount = forms.DecimalField(
        min_value=0, max_value=MAX_WEEKLY_SAVINGS,
        required=False, initial=Decimal('0.00'),
        label="Saving",
        widget=forms.NumberInput(attrs={'placeholder': '10,000–50,000', 'min': '10000', 'max': '50000', 'step': '100'}),
    )
    welfare_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Welfare",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    annual_subscription_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Annual Subscription",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    membership_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Membership",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    fine_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Fine",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    shares_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Shares",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    loan_repayment_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Loan Repayment",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )

    class Meta:
        model = DepositSubmission
        fields = [
            'account', 'payment_date', 'payment_time',
            'saving_amount', 'welfare_amount', 'annual_subscription_amount', 'membership_amount', 'fine_amount', 'shares_amount', 'loan_repayment_amount',
            'proof', 'remarks',
        ]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self.payment_week = kwargs.pop('payment_week', None)
        super().__init__(*args, **kwargs)
        self._user = user
        if user:
            self.fields['account'].queryset = SavingsAccount.objects.filter(owner=user, is_active=True)
            # Keep loan_repayment in choices — JS will show/hide per selected account.
            # Remove it entirely only if the user has zero approved loans anywhere.
            has_any_loan = LoanRequest.objects.filter(member=user, status='APPROVED').exists()
            if not has_any_loan:
                self.fields['selected_purposes'].choices = [
                    choice for choice in self.fields['selected_purposes'].choices if choice[0] != 'loan_repayment'
                ]
                self.fields['loan_repayment_amount'].widget = forms.HiddenInput()
                self.fields['loan_repayment_amount'].required = False

        initial_purposes = []
        if self.instance and self.instance.pk:
            if (self.instance.saving_amount or Decimal('0.00')) > 0:
                initial_purposes.append('saving')
            if (self.instance.welfare_amount or Decimal('0.00')) > 0:
                initial_purposes.append('welfare')
            if (self.instance.annual_subscription_amount or Decimal('0.00')) > 0:
                initial_purposes.append('annual_subscription')
            if (self.instance.membership_amount or Decimal('0.00')) > 0:
                initial_purposes.append('membership')
            if (self.instance.fine_amount or Decimal('0.00')) > 0:
                initial_purposes.append('fine')
            if (self.instance.shares_amount or Decimal('0.00')) > 0:
                initial_purposes.append('shares')
            if (self.instance.loan_repayment_amount or Decimal('0.00')) > 0:
                initial_purposes.append('loan_repayment')
        self.fields['selected_purposes'].initial = initial_purposes

    def clean(self):
        cleaned_data = super().clean()
        selected_purposes = cleaned_data.get('selected_purposes') or []

        # Guard against forged submissions when loan repayment choice is hidden.
        allowed_values = {choice[0] for choice in self.fields['selected_purposes'].choices}
        invalid_values = [value for value in selected_purposes if value not in allowed_values]
        if invalid_values:
            raise forms.ValidationError("Selected purpose is not allowed for this account.")

        # Per-account check: loan repayment is only valid for accounts that have an active loan.
        if 'loan_repayment' in selected_purposes:
            account = cleaned_data.get('account')
            user = getattr(self, '_user', None)
            if account and user:
                account_has_loan = LoanRequest.objects.filter(
                    member=user, account=account, status='APPROVED'
                ).exists()
                if not account_has_loan:
                    raise forms.ValidationError(
                        "The selected account has no active loan. Loan Repayment cannot be used."
                    )

        if 'saving' in selected_purposes:
            saving_amount = cleaned_data.get('saving_amount') or Decimal('0.00')
            if saving_amount < MIN_WEEKLY_SAVINGS or saving_amount > MAX_WEEKLY_SAVINGS:
                self.add_error(
                    'saving_amount',
                    'Weekly savings must be between UGX 10,000 and UGX 50,000.',
                )
            account = cleaned_data.get('account')
            user = getattr(self, '_user', None)
            if user and account and self.payment_week:
                existing = weekly_savings_total(
                    user, account, self.payment_week, statuses=('PENDING', 'APPROVED')
                )
                if existing >= MIN_WEEKLY_SAVINGS:
                    self.add_error('saving_amount', 'This week is already paid or awaiting approval.')

        total = Decimal('0.00')
        for purpose_key, amount_field in PURPOSE_AMOUNT_FIELDS.items():
            amount_value = cleaned_data.get(amount_field) or Decimal('0.00')

            if purpose_key in selected_purposes:
                if amount_value <= 0:
                    self.add_error(amount_field, "Enter an amount for this selected purpose.")
                else:
                    total += amount_value
            else:
                if amount_value > 0:
                    self.add_error(amount_field, "Tick this purpose to use this amount.")
                cleaned_data[amount_field] = Decimal('0.00')

        if total <= 0:
            raise forms.ValidationError("Please enter an amount for at least one purpose.")
        cleaned_data['amount'] = total
        return cleaned_data


class DirectDepositForm(forms.ModelForm):
    payment_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    payment_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))
    payment_week = forms.DateField(required=False, widget=forms.HiddenInput())
    selected_weeks = forms.MultipleChoiceField(
        choices=(), required=False, widget=forms.CheckboxSelectMultiple,
        label='Savings weeks',
    )
    amount_received = forms.DecimalField(
        min_value=0,
        required=False,
        label='Amount received',
        widget=forms.NumberInput(attrs={'placeholder': 'Optional', 'min': '0', 'step': '100'}),
        help_text='If entered, it must be fully allocated before the deposit can be saved.',
    )
    member = forms.ModelChoiceField(queryset=MemberProfile.objects.filter(is_superuser=False), label="Member")
    account = forms.ModelChoiceField(queryset=SavingsAccount.objects.none(), required=False)
    proof = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        error_messages={
            'invalid_image': 'Upload proof of payment as an image. PDF files are not accepted; use JPG, JPEG, PNG, or another image file.',
        },
    )
    selected_purposes = forms.MultipleChoiceField(
        choices=PURPOSE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Deposit Purpose",
    )
    saving_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Saving",
        widget=forms.HiddenInput(),
    )
    welfare_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Welfare",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    annual_subscription_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Annual Subscription",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    membership_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Membership",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    fine_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Fine",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    shares_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Shares",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )
    loan_repayment_amount = forms.DecimalField(
        min_value=0, required=False, initial=Decimal('0.00'),
        label="Loan Repayment",
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
    )

    class Meta:
        model = DepositSubmission
        fields = [
            'member', 'account', 'payment_week', 'payment_date', 'payment_time',
            'saving_amount', 'welfare_amount', 'annual_subscription_amount', 'membership_amount', 'fine_amount', 'shares_amount', 'loan_repayment_amount',
            'proof', 'remarks',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        settings = GroupSettings.get_active()
        week_choices = []
        if settings:
            saving_week = current_saving_week(settings.week_one_start)
            weeks = [saving_week.cycle_start + timedelta(weeks=index) for index in range(saving_week.week_number)]
            week_choices = [
                (week.isoformat(), f'Week {index} · Fri {week:%d %b}')
                for index, week in enumerate(weeks, start=1)
            ]
            self.fields['selected_weeks'].choices = week_choices

        member_id = None
        if self.is_bound:
            member_id = self.data.get(self.add_prefix('member'))
        if not member_id:
            member_id = self.initial.get('member') or getattr(self.instance, 'member_id', None)

        if member_id:
            self.fields['account'].queryset = SavingsAccount.objects.filter(owner_id=member_id, is_active=True)
        else:
            self.fields['account'].queryset = SavingsAccount.objects.none()
        self.fields['account'].empty_label = '-- Select member first --'

        account_id = self.data.get(self.add_prefix('account')) if self.is_bound else self.initial.get('account')
        selected_values = set(self.data.getlist(self.add_prefix('selected_weeks'))) if self.is_bound else set()
        account = SavingsAccount.objects.filter(pk=account_id, owner_id=member_id).first() if account_id else None
        self.week_options = []
        member = MemberProfile.objects.filter(pk=member_id, is_superuser=False).first() if member_id else None
        for value, label in week_choices:
            week = datetime.date.fromisoformat(value)
            is_paid = bool(member and weekly_savings_total(member, account, week) >= MIN_WEEKLY_SAVINGS)
            self.week_options.append({
                'value': value,
                'label': label,
                'is_paid': is_paid,
                'selected': value in selected_values and not is_paid,
                'amount': self.data.get(f'week_amount_{value}', '') if self.is_bound else '',
            })

        initial_purposes = []
        if self.instance and self.instance.pk:
            if (self.instance.saving_amount or Decimal('0.00')) > 0:
                initial_purposes.append('saving')
            if (self.instance.welfare_amount or Decimal('0.00')) > 0:
                initial_purposes.append('welfare')
            if (self.instance.annual_subscription_amount or Decimal('0.00')) > 0:
                initial_purposes.append('annual_subscription')
            if (self.instance.membership_amount or Decimal('0.00')) > 0:
                initial_purposes.append('membership')
            if (self.instance.fine_amount or Decimal('0.00')) > 0:
                initial_purposes.append('fine')
            if (self.instance.shares_amount or Decimal('0.00')) > 0:
                initial_purposes.append('shares')
            if (self.instance.loan_repayment_amount or Decimal('0.00')) > 0:
                initial_purposes.append('loan_repayment')
        self.fields['selected_purposes'].initial = initial_purposes

    def clean(self):
        cleaned_data = super().clean()
        member = cleaned_data.get('member')
        account = cleaned_data.get('account')
        selected_purposes = cleaned_data.get('selected_purposes') or []
        if member and not account:
            sole_account = SavingsAccount.objects.filter(owner=member, is_active=True).order_by('id').first()
            if SavingsAccount.objects.filter(owner=member, is_active=True).count() == 1:
                account = sole_account
                cleaned_data['account'] = account

        raw_week_values = self.data.getlist(self.add_prefix('selected_weeks')) if self.data else []
        if len(raw_week_values) != len(set(raw_week_values)):
            self.add_error('selected_weeks', 'Select each week only once.')
        selected_week_values = cleaned_data.get('selected_weeks') or []
        legacy_week_selection = not selected_week_values and bool(cleaned_data.get('payment_week'))
        if not selected_week_values and cleaned_data.get('payment_week'):
            selected_week_values = [cleaned_data['payment_week'].isoformat()]
        selected_weeks = [datetime.date.fromisoformat(value) for value in selected_week_values]
        cleaned_data['selected_week_dates'] = selected_weeks
        if not selected_weeks:
            self.add_error('selected_weeks', 'Select at least one savings week.')
        else:
            cleaned_data['payment_week'] = selected_weeks[0]

        if member and account and account.owner_id != member.id:
            self.add_error('account', 'Selected account does not belong to this member.')

        if member and not account:
            member_accounts_count = SavingsAccount.objects.filter(owner=member, is_active=True).count()
            if member_accounts_count > 1:
                self.add_error('account', 'Select an account for this member.')

        if member and 'loan_repayment' in selected_purposes:
            has_approved_loan = LoanRequest.objects.filter(member=member, status='APPROVED').exists()
            if not has_approved_loan:
                self.add_error('selected_purposes', 'This member has no approved loan for repayment.')

        weekly_allocations = []
        submitted_saving_amount = cleaned_data.get('saving_amount') or Decimal('0.00')
        if 'saving' in selected_purposes and selected_weeks:
            for week in selected_weeks:
                raw_amount = self.data.get(f'week_amount_{week.isoformat()}')
                if (raw_amount is None or raw_amount == '') and legacy_week_selection and len(selected_weeks) == 1:
                    amount = submitted_saving_amount
                else:
                    try:
                        amount = Decimal(str(raw_amount).replace(',', ''))
                    except (InvalidOperation, TypeError, ValueError):
                        amount = Decimal('0.00')
                if amount < MIN_WEEKLY_SAVINGS or amount > MAX_WEEKLY_SAVINGS:
                    self.add_error(
                        'selected_weeks',
                        f'Week of {week:%d %b %Y} must be between UGX 10,000 and UGX 50,000.',
                    )
                if member and weekly_savings_total(member, account, week) >= MIN_WEEKLY_SAVINGS:
                    self.add_error('selected_weeks', f'Week of {week:%d %b %Y} is already paid and locked.')
                weekly_allocations.append((week, amount))
            cleaned_data['saving_amount'] = sum(
                (amount for _week, amount in weekly_allocations), Decimal('0.00')
            )
        else:
            cleaned_data['saving_amount'] = Decimal('0.00')
        cleaned_data['weekly_allocations'] = weekly_allocations

        if not selected_purposes:
            raise forms.ValidationError("Please tick at least one purpose.")
        if len(selected_weeks) > 1 and 'saving' not in selected_purposes:
            self.add_error('selected_weeks', 'Multiple weeks can only be selected for a savings allocation.')

        total = Decimal('0.00')
        for purpose_key, amount_field in PURPOSE_AMOUNT_FIELDS.items():
            amount_value = cleaned_data.get(amount_field) or Decimal('0.00')

            if purpose_key in selected_purposes:
                if amount_value <= 0:
                    self.add_error(amount_field, "Enter an amount for this selected purpose.")
                else:
                    total += amount_value
            else:
                if amount_value > 0:
                    self.add_error(amount_field, "Tick this purpose to use this amount.")
                cleaned_data[amount_field] = Decimal('0.00')

        if total <= 0:
            raise forms.ValidationError("Please enter an amount for at least one purpose.")
        amount_received = cleaned_data.get('amount_received')
        if amount_received is not None and amount_received != total:
            difference = abs(amount_received - total)
            label = 'remaining' if amount_received < total else 'overpayment'
            self.add_error(
                'amount_received',
                f'UGX {difference:,.0f} is {label}. Adjust the allocations so the amount received equals the total payable.',
            )
        cleaned_data['amount'] = total
        return cleaned_data
