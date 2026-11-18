from django import forms

from groupcore.models import SavingsAccount
from .models import LoanGuarantorApproval, LoanRepayment, LoanRequest


class LoanRequestForm(forms.ModelForm):
    guarantor_accounts = forms.ModelMultipleChoiceField(
        queryset=SavingsAccount.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label='Select three guarantor savings accounts',
        help_text='Choose exactly three active savings accounts. Multiple accounts may belong to the same member.',
    )

    class Meta:
        model = LoanRequest
        fields = ['account', 'principal', 'duration_months', 'purpose']
        labels = {
            'principal': 'Requested Amount',
        }
        widgets = {
            'principal': forms.NumberInput(attrs={'data-validate': 'money', 'min': '1', 'step': '0.01'}),
            'duration_months': forms.NumberInput(attrs={'data-validate': 'integer', 'min': '1'}),
            'purpose': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields['duration_months'].required = True
        if user:
            self.fields['account'].queryset = SavingsAccount.objects.filter(owner=user, is_active=True)
            self.fields['guarantor_accounts'].queryset = (
                SavingsAccount.objects.filter(
                    is_active=True,
                    owner__is_active=True,
                    owner__is_superuser=False,
                    owner__role='MEMBER',
                )
                .exclude(owner=user)
                .select_related('owner')
                .order_by('owner__first_name', 'owner__last_name', 'owner__username', 'label')
            )

    def clean_guarantor_accounts(self):
        accounts = list(self.cleaned_data.get('guarantor_accounts') or [])
        raw_values = []

        if self.data:
            raw_values = [
                value for value in self.data.getlist(self.add_prefix('guarantor_accounts'))
                if value
            ]

        if len(raw_values) != len(set(raw_values)):
            raise forms.ValidationError('Select each guarantor only once.')

        if len(accounts) != 3:
            raise forms.ValidationError('Exactly three guarantor savings accounts are required.')

        if self.user and any(account.owner_id == self.user.id for account in accounts):
            raise forms.ValidationError('You cannot select one of your own accounts as a guarantor.')

        if any(account.owner.role != 'MEMBER' for account in accounts):
            raise forms.ValidationError('Leadership and management accounts cannot act as guarantors.')

        if any(not account.is_active or not account.owner.is_active for account in accounts):
            raise forms.ValidationError('Every guarantor savings account and its owner must be active.')

        return accounts


class TreasurerRateForm(forms.ModelForm):
    class Meta:
        model = LoanRequest
        fields = ['monthly_interest_rate']
        labels = {'monthly_interest_rate': 'Interest Rate (% / month)'}
        widgets = {
            'monthly_interest_rate': forms.NumberInput(attrs={'data-validate': 'decimal', 'min': '0', 'max': '100', 'step': '0.01'}),
        }


class GuarantorDecisionForm(forms.ModelForm):
    class Meta:
        model = LoanGuarantorApproval
        fields = ['comments']
        widgets = {
            'comments': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Comments (optional)'}),
        }


class LoanRepaymentForm(forms.ModelForm):
    class Meta:
        model = LoanRepayment
        fields = ['amount', 'paid_on', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={'data-validate': 'money', 'min': '0.01', 'step': '0.01'}),
            'paid_on': forms.DateInput(attrs={'type': 'date'}),
        }
