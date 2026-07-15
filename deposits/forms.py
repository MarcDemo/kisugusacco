from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.utils import timezone

from .models import DepositSubmission
from groupcore.models import GroupSettings, MemberProfile, SavingsAccount
from groupcore.week_cycle import current_saving_week
from loans.models import LoanRequest
from deposits.rules import (
    MAX_WEEKLY_SAVINGS,
    MIN_WEEKLY_SAVINGS,
    fine_week_options,
    saving_year_weeks,
    saving_week_statuses,
    weekly_savings_total,
    weekly_savings_totals_by_week,
)


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
    selected_weeks = forms.MultipleChoiceField(
        choices=(), required=False, widget=forms.CheckboxSelectMultiple,
        label='Savings weeks',
    )
    selected_fine_weeks = forms.MultipleChoiceField(
        choices=(), required=False, widget=forms.CheckboxSelectMultiple,
        label='Fine weeks',
    )
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
        min_value=0,
        required=False, initial=Decimal('0.00'),
        label="Saving",
        widget=forms.NumberInput(attrs={'placeholder': 'Total savings', 'min': '10000', 'step': '100'}),
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

    def _data_values(self, field_name):
        if not self.data:
            return []
        key = self.add_prefix(field_name)
        if hasattr(self.data, 'getlist'):
            return self.data.getlist(key)
        value = self.data.get(key, [])
        return list(value) if isinstance(value, (list, tuple)) else [value]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self.payment_week = kwargs.pop('payment_week', None)
        self.allow_backdated_payment = kwargs.pop('allow_backdated_payment', False)
        super().__init__(*args, **kwargs)
        self._user = user
        self.today = timezone.localdate()
        self.group_settings = GroupSettings.get_active()
        self.saving_week = None
        self.saving_weeks = []
        if self.group_settings:
            self.saving_week, self.saving_weeks = saving_year_weeks(
                self.group_settings.week_one_start,
                self.today,
            )
        self.fields['selected_weeks'].choices = [
            (week.isoformat(), f'Week {index} · {week:%A %d %b}')
            for index, week in enumerate(self.saving_weeks, start=1)
        ]
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

        account_id = self.data.get(self.add_prefix('account')) if self.is_bound else self.initial.get('account')
        account_id = getattr(account_id, 'pk', account_id)
        account = self.fields['account'].queryset.filter(pk=account_id).first() if account_id else None
        if not account and self.fields['account'].queryset.count() == 1:
            account = self.fields['account'].queryset.first()
        self._account = account
        self._submitted_week_values = self._data_values('selected_weeks') if self.is_bound else []
        self._submitted_fine_values = self._data_values('selected_fine_weeks') if self.is_bound else []
        self._saving_statuses = saving_week_statuses(
            user,
            account,
            self.saving_weeks,
            self.today,
            statuses=('PENDING', 'APPROVED'),
        )
        # Fine obligations can refer to an earlier saving cycle; unlike the
        # savings picker, the fine picker must not hide an outstanding week
        # merely because it is outside the current cycle.
        self.fine_options_by_week = fine_week_options(user, account)
        self.fields['selected_fine_weeks'].choices = [
            (week.isoformat(), f'Fine · {week:%A %d %b %Y}')
            for week in sorted(self.fine_options_by_week)
        ]
        self.week_options = []
        for index, week in enumerate(self.saving_weeks, start=1):
            status = self._saving_statuses.get(week, {}).get('status', 'available')
            fine_state = self.fine_options_by_week.get(week, {})
            self.week_options.append({
                'value': week.isoformat(),
                'label': f'Week {index} · {week:%A %d %b}',
                'date_label': f'{week:%A} {week.day} {week:%B %Y}',
                'accessible_label': f'Week {index}, {week:%A} {week.day} {week:%B %Y}',
                'week_number': index,
                'month': week.month,
                'month_name': week.strftime('%B'),
                'year': week.year,
                'day': week.day,
                'savings_status': status,
                'fine_status': fine_state.get('status', 'none'),
                'fine_outstanding': fine_state.get('outstanding', Decimal('0.00')),
                'is_future': week > self.today,
                'is_current': week <= self.today < week + timedelta(days=7),
                'selectable': status not in ('paid_on_time', 'paid_late'),
                'selected': week.isoformat() in set(self._submitted_week_values),
                'amount': self.data.get(f'week_amount_{week.isoformat()}', '') if self.is_bound else '',
            })
        self.fine_options = []
        for index, week in enumerate(sorted(self.fine_options_by_week), start=1):
            state = self.fine_options_by_week.get(week)
            if not state:
                continue
            self.fine_options.append({
                'value': week.isoformat(),
                'label': f'Week {index} · {week:%A %d %b}',
                'accessible_label': f'Fine for Week {index}, {week:%A} {week.day} {week:%B %Y}',
                'week_number': index,
                'month': week.month,
                'month_name': week.strftime('%B'),
                'year': week.year,
                'day': week.day,
                'status': state['status'],
                'selectable': state['selectable'],
                'selected': week.isoformat() in set(self._submitted_fine_values) and state['selectable'],
                'outstanding': state['outstanding'],
                'fine_allocations': state['fine_allocations'],
            })
        self.has_outstanding_fines = any(item['selectable'] for item in self.fine_options)

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

        selected_weeks = []
        weekly_allocations = []
        if 'saving' in selected_purposes:
            saving_amount = cleaned_data.get('saving_amount') or Decimal('0.00')
            raw_week_values = self._submitted_week_values
            allowed_weeks = set(self.saving_weeks)
            if len(raw_week_values) != len(set(raw_week_values)):
                self.add_error('selected_weeks', 'Select each week only once.')
            for value in raw_week_values:
                try:
                    week = date.fromisoformat(value)
                except (TypeError, ValueError):
                    self.add_error('selected_weeks', 'Select savings weeks from the active saving year only.')
                    continue
                if week not in allowed_weeks:
                    self.add_error('selected_weeks', 'Select savings weeks from the active saving year only.')
                elif week not in selected_weeks:
                    selected_weeks.append(week)
            if not selected_weeks and self.payment_week:
                selected_weeks = [self.payment_week]
            if not selected_weeks:
                self.add_error('selected_weeks', 'Select at least one savings week.')
            else:
                cleaned_data['payment_week'] = selected_weeks[0]
                if not self.allow_backdated_payment:
                    current_week = current_saving_week(
                        self.group_settings.week_one_start,
                        self.today,
                    ).week_start if self.group_settings else self.today
                    if any(week < current_week for week in selected_weeks):
                        payment_date = cleaned_data.get('payment_date')
                        if payment_date and payment_date < self.today:
                            self.add_error(
                                'payment_date',
                                'Members cannot backdate payments when backfilling a past savings week. '
                                'Use today’s payment date or ask the treasurer to record the historical date.',
                            )
            if saving_amount < MIN_WEEKLY_SAVINGS:
                self.add_error('saving_amount', 'Savings total must be at least UGX 10,000.')
            for week in selected_weeks:
                raw_amount = self.data.get(f'week_amount_{week.isoformat()}')
                if raw_amount in (None, '') and len(selected_weeks) == 1:
                    amount = saving_amount
                else:
                    try:
                        amount = Decimal(str(raw_amount).replace(',', ''))
                    except (InvalidOperation, TypeError, ValueError):
                        amount = Decimal('0.00')
                        self.add_error('selected_weeks', f'Enter a valid allocation for Week {week:%d %b %Y}.')
                if amount < MIN_WEEKLY_SAVINGS or amount > MAX_WEEKLY_SAVINGS:
                    self.add_error('selected_weeks', f'Week of {week:%d %b %Y} must be between UGX 10,000 and UGX 50,000.')
                status = self._saving_statuses.get(week, {})
                if status.get('total', Decimal('0.00')) >= MIN_WEEKLY_SAVINGS:
                    self.add_error('selected_weeks', f'Week of {week:%d %b %Y} is already paid or awaiting approval.')
                weekly_allocations.append((week, amount))
            allocated_savings = sum((amount for _week, amount in weekly_allocations), Decimal('0.00'))
            if allocated_savings != saving_amount:
                self.add_error('selected_weeks', 'Weekly allocations must equal the Savings total.')
        else:
            cleaned_data['saving_amount'] = Decimal('0.00')
            payment_date = cleaned_data.get('payment_date')
            if self.group_settings and payment_date:
                payment_week = current_saving_week(self.group_settings.week_one_start, payment_date).week_start
                selected_weeks = [payment_week]
                cleaned_data['payment_week'] = payment_week

        fine_allocations = []
        if 'fine' in selected_purposes:
            fine_by_value = {item['value']: item for item in self.fine_options}
            selected_fine_values = []
            for value in self._submitted_fine_values:
                option = fine_by_value.get(value)
                if not option or not option['selectable']:
                    self.add_error('selected_fine_weeks', 'Select only outstanding fine weeks.')
                    continue
                if value not in selected_fine_values:
                    selected_fine_values.append(value)
                    fine_allocations.extend(
                        (allocation['id'], allocation['amount'])
                        for allocation in option['fine_allocations']
                    )
            if not selected_fine_values:
                self.add_error('selected_fine_weeks', 'Select at least one outstanding fine week.')
            cleaned_data['fine_amount'] = sum((amount for _fine_id, amount in fine_allocations), Decimal('0.00'))
        else:
            cleaned_data['fine_amount'] = Decimal('0.00')
        cleaned_data['selected_week_dates'] = selected_weeks
        cleaned_data['weekly_allocations'] = weekly_allocations
        cleaned_data['fine_allocations'] = fine_allocations

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
    selected_fine_weeks = forms.MultipleChoiceField(
        choices=(), required=False, widget=forms.CheckboxSelectMultiple,
        label='Fine weeks',
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
        min_value=0, max_digits=10, decimal_places=2,
        required=False, initial=Decimal('0.00'),
        label="Savings total",
        widget=forms.NumberInput(attrs={
            'placeholder': 'Total savings to allocate',
            'min': '10000',
            'step': '100',
            'inputmode': 'decimal',
        }),
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

    def _data_values(self, field_name):
        if not self.data:
            return []
        key = self.add_prefix(field_name)
        if hasattr(self.data, 'getlist'):
            return self.data.getlist(key)
        value = self.data.get(key, [])
        return list(value) if isinstance(value, (list, tuple)) else [value]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.today = timezone.localdate()
        self.group_settings = GroupSettings.get_active()
        self.saving_week = None
        self.saving_weeks = []
        if self.group_settings:
            self.saving_week, self.saving_weeks = saving_year_weeks(
                self.group_settings.week_one_start,
                self.today,
            )

        week_choices = [
            (week.isoformat(), f'Week {index} · {week:%A %d %b}')
            for index, week in enumerate(self.saving_weeks, start=1)
        ]
        self.fields['selected_weeks'].choices = week_choices

        self._submitted_week_values = self._data_values('selected_weeks') if self.is_bound else []
        raw_purposes = set(self._data_values('selected_purposes')) if self.is_bound else set()
        if self.is_bound and 'saving' not in raw_purposes:
            # Week controls are savings-only. Ignore stale or forged calendar data
            # for deposits whose selected purposes do not include savings.
            mutable_data = self.data.copy()
            selected_weeks_key = self.add_prefix('selected_weeks')
            if hasattr(mutable_data, 'setlist'):
                mutable_data.setlist(selected_weeks_key, [])
            else:
                mutable_data[selected_weeks_key] = []
            mutable_data[self.add_prefix('payment_week')] = ''
            self.data = mutable_data

        member_id = None
        if self.is_bound:
            member_id = self.data.get(self.add_prefix('member'))
        if not member_id:
            member_id = self.initial.get('member') or getattr(self.instance, 'member_id', None)
        member_id = getattr(member_id, 'pk', member_id)

        active_accounts = SavingsAccount.objects.none()
        if member_id:
            active_accounts = SavingsAccount.objects.filter(owner_id=member_id, is_active=True)
            self.fields['account'].queryset = active_accounts
        else:
            self.fields['account'].queryset = active_accounts
        self.fields['account'].empty_label = '-- Select member first --'

        account_id = (
            self.data.get(self.add_prefix('account'))
            if self.is_bound else self.initial.get('account')
        )
        account_id = getattr(account_id, 'pk', account_id)
        account = active_accounts.filter(pk=account_id).first() if account_id else None
        if member_id and not account:
            possible_accounts = list(active_accounts.order_by('id')[:2])
            if len(possible_accounts) == 1:
                account = possible_accounts[0]

        selected_values = set(self._data_values('selected_weeks')) if self.is_bound else set()
        selected_fine_values = set(self._data_values('selected_fine_weeks')) if self.is_bound else set()
        member = (
            MemberProfile.objects.filter(pk=member_id, is_superuser=False).first()
            if member_id else None
        )
        paid_totals = weekly_savings_totals_by_week(
            member,
            account,
            self.saving_weeks,
        )
        savings_statuses = saving_week_statuses(
            member,
            account,
            self.saving_weeks,
            self.today,
        )
        self.fine_options_by_week = fine_week_options(member, account)
        self.fields['selected_fine_weeks'].choices = [
            (week.isoformat(), f'Fine · {week:%A %d %b %Y}')
            for week in sorted(self.fine_options_by_week)
        ]
        self._paid_totals = paid_totals
        self._paid_context = (
            getattr(member, 'pk', None),
            getattr(account, 'pk', None),
        )

        self.week_options = []
        for index, week in enumerate(self.saving_weeks, start=1):
            value = week.isoformat()
            paid_amount = paid_totals.get(week, Decimal('0.00'))
            week_status = savings_statuses.get(week, {}).get('status', 'available')
            is_paid = week_status in ('paid_on_time', 'paid_late')
            is_future = week > self.today
            is_current = week <= self.today < week + timedelta(days=7)
            selectable = not is_paid
            date_label = f'{week:%A} {week.day} {week:%B %Y}'
            fine_state = self.fine_options_by_week.get(week, {})
            self.week_options.append({
                'value': value,
                'label': f'Week {index} · {week:%A %d %b}',
                'date_label': date_label,
                'accessible_label': f'Week {index}, {date_label}',
                'week_number': index,
                'month': week.month,
                'month_name': week.strftime('%B'),
                'year': week.year,
                'day': week.day,
                'paid_amount': paid_amount,
                'is_paid': is_paid,
                'savings_status': week_status,
                'fine_status': fine_state.get('status', 'none'),
                'fine_outstanding': fine_state.get('outstanding', Decimal('0.00')),
                'is_future': is_future,
                'is_current': is_current,
                'is_available': selectable,
                'selectable': selectable,
                'selected': value in selected_values and selectable,
                'amount': self.data.get(f'week_amount_{value}', '') if self.is_bound else '',
            })

        self.fine_options = []
        for index, week in enumerate(sorted(self.fine_options_by_week), start=1):
            fine_state = self.fine_options_by_week.get(week)
            if not fine_state:
                continue
            self.fine_options.append({
                'value': week.isoformat(),
                'label': f'Week {index} · {week:%A %d %b}',
                'accessible_label': f'Fine for Week {index}, {week:%A} {week.day} {week:%B %Y}',
                'week_number': index,
                'month': week.month,
                'month_name': week.strftime('%B'),
                'year': week.year,
                'day': week.day,
                'status': fine_state['status'],
                'selectable': fine_state['selectable'],
                'selected': week.isoformat() in selected_fine_values and fine_state['selectable'],
                'outstanding': fine_state['outstanding'],
                'fine_allocations': fine_state['fine_allocations'],
            })
        self.has_outstanding_fines = any(item['selectable'] for item in self.fine_options)

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
            possible_accounts = list(
                SavingsAccount.objects.filter(owner=member, is_active=True).order_by('id')[:2]
            )
            if len(possible_accounts) == 1:
                account = possible_accounts[0]
                cleaned_data['account'] = account

        if member and account and account.owner_id != member.id:
            self.add_error('account', 'Selected account does not belong to this member.')

        if member and not account:
            if SavingsAccount.objects.filter(owner=member, is_active=True).count() > 1:
                self.add_error('account', 'Select an account for this member.')

        if member and 'loan_repayment' in selected_purposes:
            has_approved_loan = LoanRequest.objects.filter(member=member, status='APPROVED').exists()
            if not has_approved_loan:
                self.add_error('selected_purposes', 'This member has no approved loan for repayment.')

        weekly_allocations = []
        submitted_saving_amount = cleaned_data.get('saving_amount') or Decimal('0.00')
        selected_weeks = []
        saving_selected = 'saving' in selected_purposes

        if saving_selected:
            raw_week_values = self._submitted_week_values
            if len(raw_week_values) != len(set(raw_week_values)):
                self.add_error('selected_weeks', 'Select each week only once.')

            allowed_weeks = set(self.saving_weeks)
            invalid_week_values = []
            for value in raw_week_values:
                try:
                    parsed_week = date.fromisoformat(value)
                except (TypeError, ValueError):
                    invalid_week_values.append(value)
                    continue
                if parsed_week not in allowed_weeks:
                    invalid_week_values.append(value)
            if invalid_week_values:
                self.add_error(
                    'selected_weeks',
                    'Select savings weeks from the active saving year only.',
                )

            selected_week_values = cleaned_data.get('selected_weeks') or []
            legacy_week_selection = (
                not raw_week_values
                and not selected_week_values
                and bool(cleaned_data.get('payment_week'))
            )
            if legacy_week_selection:
                selected_week_values = [cleaned_data['payment_week'].isoformat()]

            seen_weeks = set()
            for value in selected_week_values:
                try:
                    week = date.fromisoformat(value)
                except (TypeError, ValueError):
                    continue
                if week not in seen_weeks:
                    selected_weeks.append(week)
                    seen_weeks.add(week)

            if not selected_weeks:
                self.add_error('selected_weeks', 'Select at least one savings week.')
            else:
                cleaned_data['payment_week'] = selected_weeks[0]

            if submitted_saving_amount < MIN_WEEKLY_SAVINGS:
                self.add_error(
                    'saving_amount',
                    'Savings total must be at least UGX 10,000.',
                )

            paid_context = (
                getattr(member, 'pk', None),
                getattr(account, 'pk', None),
            )
            if paid_context == self._paid_context:
                paid_totals = self._paid_totals
            else:
                paid_totals = weekly_savings_totals_by_week(
                    member,
                    account,
                    self.saving_weeks,
                )

            for week in selected_weeks:
                raw_amount = self.data.get(f'week_amount_{week.isoformat()}')
                if (raw_amount is None or raw_amount == '') and legacy_week_selection and len(selected_weeks) == 1:
                    amount = submitted_saving_amount
                else:
                    try:
                        amount = Decimal(str(raw_amount).replace(',', ''))
                        if not amount.is_finite() or amount.as_tuple().exponent < -2:
                            raise InvalidOperation
                    except (InvalidOperation, TypeError, ValueError):
                        amount = Decimal('0.00')
                        self.add_error(
                            'selected_weeks',
                            f'Enter a valid allocation for the week of {week:%d %b %Y}.',
                        )
                if amount < MIN_WEEKLY_SAVINGS or amount > MAX_WEEKLY_SAVINGS:
                    self.add_error(
                        'selected_weeks',
                        f'Week of {week:%d %b %Y} must be between UGX 10,000 and UGX 50,000.',
                    )
                if week not in allowed_weeks:
                    self.add_error(
                        'selected_weeks',
                        f'Week of {week:%d %b %Y} is outside the active saving year.',
                    )
                if paid_totals.get(week, Decimal('0.00')) >= MIN_WEEKLY_SAVINGS:
                    self.add_error('selected_weeks', f'Week of {week:%d %b %Y} is already paid and locked.')
                weekly_allocations.append((week, amount))

            allocated_savings = sum(
                (amount for _week, amount in weekly_allocations), Decimal('0.00')
            )
            if allocated_savings != submitted_saving_amount:
                difference = abs(submitted_saving_amount - allocated_savings)
                direction = 'remaining' if allocated_savings < submitted_saving_amount else 'over-allocated'
                self.add_error(
                    'selected_weeks',
                    f'Weekly allocations must equal the Savings total; UGX {difference:,.0f} is {direction}.',
                )
        else:
            cleaned_data['saving_amount'] = Decimal('0.00')

            payment_date = cleaned_data.get('payment_date')
            if self.group_settings and payment_date:
                payment_week = current_saving_week(
                    self.group_settings.week_one_start,
                    payment_date,
                ).week_start
                selected_weeks = [payment_week]
                cleaned_data['payment_week'] = payment_week
            elif not self.group_settings:
                raise forms.ValidationError(
                    'Open the saving cycle in Group Settings before recording deposits.'
                )

        fine_allocations = []
        raw_fine_values = self._data_values('selected_fine_weeks')
        if 'fine' in selected_purposes:
            if len(raw_fine_values) != len(set(raw_fine_values)):
                self.add_error('selected_fine_weeks', 'Select each fine week only once.')
            fine_by_value = {item['value']: item for item in self.fine_options}
            selected_fine_values = []
            for value in raw_fine_values:
                option = fine_by_value.get(value)
                if not option or not option['selectable']:
                    self.add_error('selected_fine_weeks', 'Select only outstanding fine weeks.')
                    continue
                if value not in selected_fine_values:
                    selected_fine_values.append(value)
                    fine_allocations.extend(
                        (allocation['id'], allocation['amount'])
                        for allocation in option['fine_allocations']
                    )
            if not selected_fine_values:
                self.add_error('selected_fine_weeks', 'Select at least one outstanding fine week.')
            cleaned_data['fine_amount'] = sum(
                (amount for _fine_id, amount in fine_allocations), Decimal('0.00')
            )
        else:
            cleaned_data['fine_amount'] = Decimal('0.00')

        cleaned_data['selected_week_dates'] = selected_weeks
        cleaned_data['weekly_allocations'] = weekly_allocations
        cleaned_data['fine_allocations'] = fine_allocations

        if not selected_purposes:
            raise forms.ValidationError("Please tick at least one purpose.")

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
