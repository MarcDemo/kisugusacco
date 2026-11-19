from django import forms
from django.utils import timezone

from groupcore.member_query import alphabetical_members
from groupcore.models import MemberProfile, SavingsAccount

from .models import Withdrawal


class WithdrawalForm(forms.ModelForm):
    member = forms.ModelChoiceField(
        queryset=MemberProfile.objects.none(), label='Member'
    )
    correction_reason = forms.CharField(
        required=False,
        min_length=5,
        label='Reason for correction',
        widget=forms.Textarea(attrs={'rows': 2}),
    )

    class Meta:
        model = Withdrawal
        fields = ['member', 'account', 'amount', 'withdrawn_on', 'reason', 'reference', 'notes']
        widgets = {
            'withdrawn_on': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, require_correction_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['member'].queryset = alphabetical_members(
            MemberProfile.objects.filter(is_superuser=False, is_active=True)
        )
        member_id = (
            self.data.get('member') if self.is_bound
            else getattr(self.instance, 'member_id', None) or self.initial.get('member')
        )
        self.fields['account'].queryset = SavingsAccount.objects.filter(
            owner_id=member_id, is_active=True
        ).order_by('label')
        if not self.instance.pk:
            self.fields['withdrawn_on'].initial = timezone.localdate()
        self.fields['correction_reason'].required = require_correction_reason
        if not require_correction_reason:
            self.fields.pop('correction_reason')
        for field in self.fields.values():
            field.widget.attrs.setdefault(
                'class', 'form-select' if isinstance(field, forms.ModelChoiceField) else 'form-control'
            )

