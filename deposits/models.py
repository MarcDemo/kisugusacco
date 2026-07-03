from django.db import models
from groupcore.models import MemberProfile, SavingsAccount
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError
from datetime import timedelta

# Create your models here.


class DepositSubmission(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='deposits')
    account = models.ForeignKey(SavingsAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='deposits')
    starting_week = models.DateField(help_text="Legacy field: week this deposit starts from", null=True, blank=True)
    weeks_covered = models.PositiveIntegerField(help_text="Legacy field: how many weeks this deposit covers", default=1)
    payment_week = models.DateField(help_text="Week this saving applies to")
    # Per-purpose amounts (0 means not applicable for that purpose)
    saving_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    welfare_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    annual_subscription_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    fine_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    shares_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    loan_repayment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    # Total amount (auto-computed as the sum of per-purpose amounts)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    proof = models.ImageField(upload_to='proofs/')
    remarks = models.TextField(blank=True, null=True)
    import_reference = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        help_text="Unique source reference used to prevent duplicate historical imports.",
    )
    import_batch = models.CharField(max_length=120, blank=True, null=True)
    imported_at = models.DateTimeField(blank=True, null=True)

    payment_date = models.DateField(help_text="Date the payment was made")
    payment_time = models.TimeField(help_text="Time the payment was made")
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    submitted_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, related_name='submitted_group_deposits')
    reviewed_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_group_deposits')
    date_submitted = models.DateTimeField(auto_now_add=True)
    date_reviewed = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        member_name = self.member.username if self.member_id else "Unknown member"
        return f"{member_name} - UGX {self.amount} ({self.status})"

    def clean(self):
        if self.account_id and self.member_id and self.account.owner_id != self.member_id:
            raise ValidationError({'account': 'Selected account does not belong to this member.'})

        total = (
            (self.saving_amount or Decimal('0.00')) +
            (self.welfare_amount or Decimal('0.00')) +
            (self.annual_subscription_amount or Decimal('0.00')) +
            (self.fine_amount or Decimal('0.00')) +
            (self.shares_amount or Decimal('0.00')) +
            (self.loan_repayment_amount or Decimal('0.00'))
        )
        if total <= 0:
            raise ValidationError('At least one purpose amount must be greater than zero.')

    def save(self, *args, **kwargs):
        # Auto-compute total from per-purpose amounts
        self.amount = (
            (self.saving_amount or Decimal('0.00')) +
            (self.welfare_amount or Decimal('0.00')) +
            (self.annual_subscription_amount or Decimal('0.00')) +
            (self.fine_amount or Decimal('0.00')) +
            (self.shares_amount or Decimal('0.00')) +
            (self.loan_repayment_amount or Decimal('0.00'))
        )
        if not self.payment_week and self.payment_date:
            self.payment_week = self.payment_date - timedelta(days=self.payment_date.weekday())
        if not self.starting_week:
            self.starting_week = self.payment_week
        if not self.weeks_covered:
            self.weeks_covered = 1
        super().save(*args, **kwargs)

    def get_covered_weeks(self):
        if self.payment_week:
            return [self.payment_week]
        if self.starting_week:
            return [self.starting_week]
        return []

    def purpose_breakdown(self):
        """Returns a dict of purpose -> amount for non-zero purposes."""
        breakdown = {}
        if self.saving_amount:
            breakdown['Saving'] = self.saving_amount
        if self.welfare_amount:
            breakdown['Welfare'] = self.welfare_amount
        if self.annual_subscription_amount:
            breakdown['Annual Subscription'] = self.annual_subscription_amount
        if self.fine_amount:
            breakdown['Fine'] = self.fine_amount
        if self.shares_amount:
            breakdown['Shares'] = self.shares_amount
        if self.loan_repayment_amount:
            breakdown['Loan Repayment'] = self.loan_repayment_amount
        return breakdown
