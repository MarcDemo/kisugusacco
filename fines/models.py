from django.db import models
from django.core.exceptions import ValidationError
from groupcore.models import MemberProfile
from groupcore.models import SavingsAccount

# Create your models here.
class Fine(models.Model):
    FINE_TYPES = [
        ('MISSED_WEEKLY_SAVING', 'Missed Weekly Saving'),
        ('OTHER', 'Other'),
    ]

    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='fines')
    account = models.ForeignKey(SavingsAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='fines')
    fine_type = models.CharField(max_length=30, choices=FINE_TYPES, default='OTHER')
    reference_week = models.DateField(null=True, blank=True)
    reason = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    issued_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, related_name='issued_fines')
    date_issued = models.DateField(auto_now_add=True)
    is_paid = models.BooleanField(default=False)
    remarks = models.TextField(blank=True, null=True)

    def clean(self):
        if self.account and self.member and self.account.owner_id != self.member_id:
            raise ValidationError({'account': 'Selected account does not belong to this member.'})

    def __str__(self):
        return f"{self.member.username} - UGX {self.amount} - {self.reason[:30]}"