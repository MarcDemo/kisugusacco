from django.db import models
from django.contrib.auth.models import User
from django.conf import settings

# Create your models here.
DOCUMENT_TYPES = [
    ('NID', 'National ID'),
    ('CERT', 'Certificate'),
    ('FORM', 'Form/Agreement'),
    ('MINUTES', 'Meeting Minutes'),
    ('POLICY', 'Policy Document'),
    ('OTHER', 'Other')
]

class Document(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='documents',
        null=True,
        blank=True,
        help_text="Leave empty if the document is general."
    )
    document_type = models.CharField(max_length=15, choices=DOCUMENT_TYPES)
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='documents/')
    description = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.get_document_type_display()})"