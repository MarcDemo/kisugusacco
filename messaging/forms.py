from django import forms
from .models import Message, MessageRecipient
from django.contrib.auth import get_user_model
from groupcore.models import MemberProfile

User = get_user_model()

class MessageForm(forms.ModelForm):
    recipients = forms.ModelMultipleChoiceField(
        queryset=MemberProfile.objects.none(),  # initially empty, populated in __init__
        widget=forms.CheckboxSelectMultiple(),
        label="Select Recipients"
    )

    class Meta:
        model = Message
        fields = ['recipients', 'subject', 'body']
        widgets = {
            'subject': forms.TextInput(attrs={'class': 'form-control'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        self.sender = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if self.sender:
            # Exclude the sender and superuser from the recipients list
            self.fields['recipients'].queryset = MemberProfile.objects.exclude(id=self.sender.id).exclude(
                is_superuser=True
            )

    def save(self, sender, commit=True):
        msg = Message.objects.create(
            sender=sender,
            subject=self.cleaned_data['subject'],
            body=self.cleaned_data['body']
        )
        for recipient in self.cleaned_data['recipients']:
            MessageRecipient.objects.create(message=msg, recipient=recipient)
        return msg