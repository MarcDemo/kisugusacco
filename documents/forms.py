from django import forms
from .models import Document
from django.core.exceptions import ValidationError
import os

class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['user', 'document_type', 'title', 'file', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].required = False  # Will be set manually or validated below

    def clean(self):
        cleaned_data = super().clean()
        user = cleaned_data.get('user')
        document_type = cleaned_data.get('document_type')
        file = cleaned_data.get('file')

        # If uploading a National ID
        if document_type == 'NID':
            if not user:
                raise ValidationError("Please select a user for the National ID.")

            # Ensure only one National ID per user
            if Document.objects.filter(user=user, document_type='NID').exists():
                raise ValidationError("This user already has a National ID uploaded.")

            # Ensure file is an image
            if file:
                ext = os.path.splitext(file.name)[1].lower()
                valid_extensions = ['.jpg', '.jpeg', '.png', '.webp']
                if ext not in valid_extensions:
                    raise ValidationError("National ID must be an image file (jpg, jpeg, or png).")

        return cleaned_data
