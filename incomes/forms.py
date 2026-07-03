from django import forms
from .models import OtherIncome, ShareContribution, AnnualSubscription
from groupcore.models import SavingsAccount

class OtherIncomeForm(forms.ModelForm):
    class Meta:
        model = OtherIncome
        fields = ['source', 'fine', 'amount', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fine'].queryset = self.fields['fine'].queryset.filter(is_paid=True)


class ShareContributionForm(forms.ModelForm):
    class Meta:
        model = ShareContribution
        fields = ['member', 'account', 'amount', 'remarks']

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

    def clean(self):
        cleaned_data = super().clean()
        member = cleaned_data.get('member')
        account = cleaned_data.get('account')

        if member and account and account.owner_id != member.id:
            self.add_error('account', 'Selected account does not belong to this member.')

        if member and not account:
            member_accounts_count = SavingsAccount.objects.filter(owner=member, is_active=True).count()
            if member_accounts_count > 1:
                self.add_error('account', 'Select an account for this member.')

        return cleaned_data


class AnnualSubscriptionForm(forms.ModelForm):
    class Meta:
        model = AnnualSubscription
        fields = ['member', 'year', 'amount', 'is_paid', 'paid_on']
