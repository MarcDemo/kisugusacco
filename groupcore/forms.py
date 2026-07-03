import re

from django import forms

from .models import MemberProfile


NAME_RE = re.compile(r"^[A-Za-z\s'.-]*$")
PHONE_RE = re.compile(r'^\+?[0-9\s()\-]*$')


class PersonalFieldValidationMixin:
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

    def clean_next_of_kin_name(self):
        value = self.cleaned_data.get('next_of_kin_name') or ''
        if not NAME_RE.match(value):
            raise forms.ValidationError('Next of kin name contains invalid characters.')
        return value

    def clean_next_of_kin_contact(self):
        value = self.cleaned_data.get('next_of_kin_contact') or ''
        if not PHONE_RE.match(value):
            raise forms.ValidationError('Next of kin contact contains invalid characters.')
        return value


class MemberRegistrationForm(PersonalFieldValidationMixin, forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = MemberProfile
        fields = ['username', 'email', 'role', 'password', 'phone_number', 'next_of_kin_name', 'next_of_kin_contact']
        widgets = {
            'username': forms.TextInput(attrs={'data-validate': 'username'}),
            'email': forms.EmailInput(attrs={'data-validate': 'email'}),
            'phone_number': forms.TextInput(attrs={'data-validate': 'phone'}),
            'next_of_kin_name': forms.TextInput(attrs={'data-validate': 'name'}),
            'next_of_kin_contact': forms.TextInput(attrs={'data-validate': 'phone'}),
        }


class ProfileForm(PersonalFieldValidationMixin, forms.ModelForm):
    class Meta:
        model = MemberProfile
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'next_of_kin_name', 'next_of_kin_contact', 'profile_picture']
        widgets = {
            'first_name': forms.TextInput(attrs={'data-validate': 'name'}),
            'last_name': forms.TextInput(attrs={'data-validate': 'name'}),
            'email': forms.EmailInput(attrs={'data-validate': 'email'}),
            'phone_number': forms.TextInput(attrs={'data-validate': 'phone'}),
            'next_of_kin_name': forms.TextInput(attrs={'data-validate': 'name'}),
            'next_of_kin_contact': forms.TextInput(attrs={'data-validate': 'phone'}),
        }
