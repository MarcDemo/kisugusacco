import re

from django import forms

from groupcore.models import MemberProfile, SavingsAccount


ACCOUNT_LABEL_RE = re.compile(r'^[A-Za-z0-9 _.-]+$')
NAME_RE = re.compile(r"^[A-Za-z\s'.-]*$")
PHONE_RE = re.compile(r'^\+?[0-9\s()\-]*$')


def account_labels_field():
    return forms.CharField(
        required=False,
        label='New savings accounts',
        help_text='Add one savings account at a time.',
        widget=forms.HiddenInput(),
    )


def parse_account_labels(raw_value):
    labels = []
    seen = set()

    if ',' in (raw_value or ''):
        raise forms.ValidationError('Add one savings account at a time using the Add account button.')

    for item in (raw_value or '').replace('\r', '\n').split('\n'):
        label = item.strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            raise forms.ValidationError('Savings account labels must be unique.')
        if len(label) > 20:
            raise forms.ValidationError('Savings account labels must be 20 characters or fewer.')
        if not ACCOUNT_LABEL_RE.match(label):
            raise forms.ValidationError('Savings account labels can only contain letters, numbers, spaces, hyphens, underscores, or periods.')
        seen.add(key)
        labels.append(label)

    return labels


class AccountLabelMixin:
    def clean_account_labels(self):
        labels = parse_account_labels(self.cleaned_data.get('account_labels'))
        user = getattr(self, 'instance', None)

        if labels and user and user.pk:
            existing_labels = {
                label.lower()
                for label in user.savings_accounts.values_list('label', flat=True)
            }
            for label in labels:
                if label.lower() in existing_labels:
                    raise forms.ValidationError(f'Savings account "{label}" already exists for this user.')

        return labels

    def clean_first_name(self):
        value = self.cleaned_data.get('first_name') or ''
        if not NAME_RE.match(value):
            raise forms.ValidationError('First name contains invalid characters.')
        return value

    def clean_last_name(self):
        value = self.cleaned_data.get('last_name') or ''
        if not NAME_RE.match(value):
            raise forms.ValidationError('Last name contains invalid characters.')
        return value

    def clean_phone_number(self):
        value = self.cleaned_data.get('phone_number') or ''
        if not PHONE_RE.match(value):
            raise forms.ValidationError('Phone number contains invalid characters.')
        return value

    def save_new_accounts(self, user):
        for label in self.cleaned_data.get('account_labels') or []:
            account, created = SavingsAccount.objects.get_or_create(
                owner=user,
                label=label,
                defaults={'is_active': True},
            )
            if not created and not account.is_active:
                account.is_active = True
                account.save(update_fields=['is_active'])


class AddUserForm(AccountLabelMixin, forms.ModelForm):
    account_labels = account_labels_field()
    password = forms.CharField(widget=forms.PasswordInput, label='Password')

    class Meta:
        model = MemberProfile
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'phone_number',
            'role',
            'password',
            'account_labels',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'data-validate': 'username'}),
            'first_name': forms.TextInput(attrs={'data-validate': 'name'}),
            'last_name': forms.TextInput(attrs={'data-validate': 'name'}),
            'email': forms.EmailInput(attrs={'data-validate': 'email'}),
            'phone_number': forms.TextInput(attrs={'data-validate': 'phone'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            self.save_new_accounts(user)
        return user


class EditUserForm(AccountLabelMixin, forms.ModelForm):
    account_labels = account_labels_field()
    password = forms.CharField(
        widget=forms.PasswordInput,
        label='New password',
        required=False,
        help_text='Leave blank to keep the current password.',
    )

    class Meta:
        model = MemberProfile
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'phone_number',
            'role',
            'password',
            'account_labels',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'data-validate': 'username'}),
            'first_name': forms.TextInput(attrs={'data-validate': 'name'}),
            'last_name': forms.TextInput(attrs={'data-validate': 'name'}),
            'email': forms.EmailInput(attrs={'data-validate': 'email'}),
            'phone_number': forms.TextInput(attrs={'data-validate': 'phone'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
            self.save_new_accounts(user)
        return user
