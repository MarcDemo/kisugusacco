from django import forms
from .models import Fine
from groupcore.models import MemberProfile, SavingsAccount

class FineForm(forms.ModelForm):
    class Meta:
        model = Fine
        fields = ['member', 'account', 'amount', 'reason']

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

        for field_name, field in self.fields.items():
            css_class = 'form-select' if field_name in ['member', 'account'] else 'form-control'
            existing = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f"{existing} {css_class}".strip()
        self.fields['reason'].widget.attrs.setdefault('rows', 3)

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
