from django.db import models
from django.conf import settings
from groupcore.models import MemberProfile

# Create your models here.
class Message(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='sent_messages', on_delete=models.CASCADE, null=True, blank=True)
    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='MessageRecipient',
        related_name='received_messages'
    )
    subject = models.CharField(max_length=255)
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.subject} - from {self.sender}"
    
class MessageRecipient(models.Model):
    message = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_read = models.BooleanField(default=False)

    class Meta:
        unique_together = ('message', 'recipient')

    def __str__(self):
        return f"{self.recipient.username} - {self.message.subject}"