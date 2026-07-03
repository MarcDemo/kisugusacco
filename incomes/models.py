
from django.db import models
from django.core.exceptions import ValidationError
from groupcore.models import MemberProfile, SavingsAccount
from fines.models import Fine

# Legacy model kept for compatibility with older records.
class OtherIncome(models.Model):
    SOURCE_CHOICES = [
        ('FINE', 'Fine Payment'),
        ('INTEREST', 'Interest Earned'),
        ('OTHER', 'Other Income'),
    ]

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    fine = models.ForeignKey(Fine, on_delete=models.SET_NULL, null=True, blank=True, related_name='income_record')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    date_received = models.DateField(auto_now_add=True)
    recorded_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, related_name='recorded_incomes')

    def __str__(self):
        return f"{self.source} - UGX {self.amount}"


class WelfareLedger(models.Model):
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='welfare_ledger_entries')
    year = models.PositiveIntegerField()
    weekly_contributions = models.PositiveIntegerField(default=0)
    welfare_due = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    generated_on = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ('member', 'year')

    def __str__(self):
        return f"{self.member.username} welfare {self.year} - UGX {self.welfare_due}"


class AnnualSubscription(models.Model):
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='annual_subscriptions')
    year = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=10000)
    is_paid = models.BooleanField(default=False)
    paid_on = models.DateField(null=True, blank=True)
    recorded_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_subscriptions')

    class Meta:
        unique_together = ('member', 'year')

    def __str__(self):
        return f"{self.member.username} annual subscription {self.year}"


class ShareContribution(models.Model):
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='share_contributions')
    account = models.ForeignKey(SavingsAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='share_contributions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    contribution_date = models.DateField(auto_now_add=True)
    recorded_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_shares')
    remarks = models.TextField(blank=True, null=True)

    def clean(self):
        if self.account and self.member and self.account.owner_id != self.member_id:
            raise ValidationError({'account': 'Selected account does not belong to this member.'})

    def __str__(self):
        return f"{self.member.username} share - UGX {self.amount}"