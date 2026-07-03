from django import forms

from groupcore.models import MemberProfile, SavingsAccount
from .models import LoanGuarantorApproval, LoanRepayment, LoanRequest


class LoanRequestForm(forms.ModelForm):
    guarantors = forms.ModelMultipleChoiceField(
        queryset=MemberProfile.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label='Select three guarantors',
        help_text='Choose exactly three active members. You cannot select yourself.',
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
        if user:
            self.fields['account'].queryset = SavingsAccount.objects.filter(owner=user, is_active=True)
            self.fields['guarantors'].queryset = (
                MemberProfile.objects
                .filter(is_active=True, is_superuser=False)
                .exclude(id=user.id)
                .order_by('username')
            )

    def clean_guarantors(self):
        guarantors = list(self.cleaned_data.get('guarantors') or [])
        raw_values = []

        if self.data:
            raw_values = [
                value for value in self.data.getlist(self.add_prefix('guarantors'))
                if value
            ]

        if len(raw_values) != len(set(raw_values)):
            raise forms.ValidationError('Select each guarantor only once.')

        if len(guarantors) != 3:
            raise forms.ValidationError('Exactly three guarantors are required.')

        if self.user and any(guarantor.id == self.user.id for guarantor in guarantors):
            raise forms.ValidationError('You cannot select yourself as a guarantor.')

        return guarantors


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
