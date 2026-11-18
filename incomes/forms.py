from django import forms
from .models import OtherIncome, ShareContribution, AnnualSubscription
from groupcore.models import SavingsAccount
from groupcore.models import MemberProfile
from groupcore.member_query import alphabetical_members

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
        self.fields['member'].queryset = alphabetical_members(
            MemberProfile.objects.filter(is_superuser=False)
        )

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
        fields = ['member', 'account', 'year', 'amount', 'is_paid', 'paid_on']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['member'].queryset = alphabetical_members(
            MemberProfile.objects.filter(is_superuser=False)
        )
        member_id = None
        if self.is_bound:
            member_id = self.data.get(self.add_prefix('member'))
        if not member_id:
            member_id = self.initial.get('member') or getattr(self.instance, 'member_id', None)
        if member_id:
            accounts = SavingsAccount.objects.filter(owner_id=member_id)
            if not getattr(self.instance, 'account_id', None):
                accounts = accounts.filter(is_active=True)
            self.fields['account'].queryset = accounts.order_by('label')
        else:
            self.fields['account'].queryset = SavingsAccount.objects.none()
        self.fields['account'].empty_label = '-- Select member first --'

    def clean(self):
        cleaned_data = super().clean()
        member = cleaned_data.get('member')
        account = cleaned_data.get('account')
        if member and not account and 'account' not in self.errors:
            self.add_error('account', 'Select the savings account this subscription belongs to.')
        elif member and account and account.owner_id != member.id:
            self.add_error('account', 'Selected account does not belong to this member.')
        return cleaned_data
