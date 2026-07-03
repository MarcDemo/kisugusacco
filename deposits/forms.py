from django import forms
from .models import DepositSubmission
import datetime
from groupcore.models import MemberProfile, SavingsAccount
from loans.models import LoanRequest
from datetime import timedelta
from decimal import Decimal


PURPOSE_CHOICES = [
    ('saving', 'Saving'),
    ('welfare', 'Welfare'),
    ('annual_subscription', 'Annual Subscription'),
    ('fine', 'Fine'),
    ('shares', 'Shares'),
    ('loan_repayment', 'Loan Repayment'),
]

PURPOSE_AMOUNT_FIELDS = {
    'saving': 'saving_amount',
    'welfare': 'welfare_amount',
    'annual_subscription': 'annual_subscription_amount',
    'fine': 'fine_amount',
    'shares': 'shares_amount',
    'loan_repayment': 'loan_repayment_amount',
}


class DepositSubmissionForm(forms.ModelForm):
    payment_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    payment_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))
    account = forms.ModelChoiceField(queryset=SavingsAccount.objects.none(), required=True, empty_label="-- Select Account --")
    proof = forms.ImageField(
        required=True,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        error_messages={
            'required': 'Please upload proof of payment as an image.',
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
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
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
            'saving_amount', 'welfare_amount', 'annual_subscription_amount', 'fine_amount', 'shares_amount', 'loan_repayment_amount',
            'proof', 'remarks',
        ]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
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
    payment_week = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    member = forms.ModelChoiceField(queryset=MemberProfile.objects.all(), label="Member")
    account = forms.ModelChoiceField(queryset=SavingsAccount.objects.none(), required=False)
    proof = forms.ImageField(
        required=True,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        error_messages={
            'required': 'Please upload proof of payment as an image.',
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
        widget=forms.NumberInput(attrs={'placeholder': '0', 'min': '0', 'step': '100'}),
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
            'saving_amount', 'welfare_amount', 'annual_subscription_amount', 'fine_amount', 'shares_amount', 'loan_repayment_amount',
            'proof', 'remarks',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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

        initial_purposes = []
        if self.instance and self.instance.pk:
            if (self.instance.saving_amount or Decimal('0.00')) > 0:
                initial_purposes.append('saving')
            if (self.instance.welfare_amount or Decimal('0.00')) > 0:
                initial_purposes.append('welfare')
            if (self.instance.annual_subscription_amount or Decimal('0.00')) > 0:
                initial_purposes.append('annual_subscription')
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
