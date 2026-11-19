from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from groupcore.models import MemberProfile, SavingsAccount


class Withdrawal(models.Model):
    member = models.ForeignKey(
        MemberProfile, on_delete=models.PROTECT, related_name='savings_withdrawals'
    )
    account = models.ForeignKey(
        SavingsAccount, on_delete=models.PROTECT, related_name='withdrawals'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    withdrawn_on = models.DateField()
    reason = models.TextField()
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recorded_withdrawals',
    )
    is_voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='voided_withdrawals',
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-withdrawn_on', '-id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='withdrawal_amount_positive',
            ),
        ]

    def clean(self):
        super().clean()
        if self.amount is None or self.amount <= Decimal('0.00'):
            raise ValidationError({'amount': 'Withdrawal amount must be greater than zero.'})
        if self.account_id and self.member_id and self.account.owner_id != self.member_id:
            raise ValidationError({'account': 'The selected account does not belong to this member.'})
        if not ' '.join((self.reason or '').split()):
            raise ValidationError({'reason': 'Enter the member’s reason for withdrawing.'})

    def __str__(self):
        state = 'voided' if self.is_voided else 'active'
        return f'{self.account} — UGX {self.amount:,.0f} ({state})'


class WithdrawalRevision(models.Model):
    withdrawal = models.ForeignKey(
        Withdrawal, on_delete=models.PROTECT, related_name='revisions'
    )
    revision_number = models.PositiveIntegerField()
    before_data = models.JSONField()
    after_data = models.JSONField()
    reason = models.TextField()
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='withdrawal_revisions',
    )
    edited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['revision_number', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['withdrawal', 'revision_number'],
                name='unique_withdrawal_revision_number',
            ),
        ]

