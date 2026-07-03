from django.contrib import admin
from .models import Message, MessageRecipient

# Register your models here.
admin.site.register(Message)
admin.site.register(MessageRecipient)