from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.conf import settings
from decimal import Decimal



# Create your models here.

class MemberProfile(AbstractUser):
    ROLE_CHOICES = [
        ('MEMBER', 'Member'),
        ('TREASURER', 'Treasurer'),
        ('CHAIRMAN', 'Chairman'),
        ('VICE_CHAIRMAN', 'Vice Chairman'),
        ('SECRETARY', 'Secretary'),
        ('MOBILIZER', 'Mobilizer'),
        ('OVERSEER', 'Overseer'),
    ]

    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default='MEMBER')

    
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    next_of_kin_name = models.CharField(max_length=100, blank=True, null=True)
    next_of_kin_contact = models.CharField(max_length=20, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    

    def is_member(self):
        return self.role == 'MEMBER'

    def is_treasurer(self):
        return self.role == 'TREASURER'

    def is_chairman(self):
        return self.role == 'CHAIRMAN'

    def is_vice_chairman(self):
        return self.role == 'VICE_CHAIRMAN'
    
    def is_secretary(self):
        return self.role == 'SECRETARY'
    
    def is_mobilizer(self):
        return self.role == 'MOBILIZER'

    def is_overseer(self):
        return self.role == 'OVERSEER'

    def __str__(self):
        return self.get_full_name().strip() or self.username
    
class GroupSettings(models.Model):
    week_one_start = models.DateField(help_text="The date of the first week (Week 1)")

    @classmethod
    def get_active(cls):
        return cls.objects.order_by('pk').first()

    def clean(self):
        super().clean()
        if self.week_one_start and self.week_one_start.weekday() != 4:
            raise ValidationError({
                'week_one_start': 'Week 1 start must be a Friday.',
            })
        if GroupSettings.objects.exclude(pk=self.pk).exists():
            raise ValidationError("Only one group setting record is allowed.")

    def save(self, *args, **kwargs):
        if self.pk is None:
            existing = GroupSettings.get_active()
            if existing:
                self.pk = existing.pk
                kwargs.pop('force_insert', None)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Group Settings (Week 1 Start: {self.week_one_start})"

    class Meta:
        verbose_name = "Group Setting"
        verbose_name_plural = "Group Settings"


class SavingsAccount(models.Model):
    owner = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='savings_accounts')
    label = models.CharField(max_length=100, help_text="e.g. A, B, C, or an account/member name")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('owner', 'label')
        ordering = ['owner__first_name', 'owner__last_name', 'owner__username', 'label']

    def __str__(self):
        owner_name = self.owner.get_full_name().strip() or self.owner.username
        return f"{owner_name} — {self.label}"


class FinancialRecordRevision(models.Model):
    record_type = models.CharField(max_length=60)
    object_id = models.PositiveBigIntegerField()
    revision_number = models.PositiveIntegerField()
    before_data = models.JSONField()
    after_data = models.JSONField()
    reason = models.TextField()
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='financial_record_revisions',
    )
    edited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['revision_number', 'edited_at', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['record_type', 'object_id', 'revision_number'],
                name='unique_financial_record_revision',
            ),
        ]


class FinancialYearClose(models.Model):
    STATE_OPEN = 'OPEN'
    STATE_LOCKED = 'LOCKED_REVIEW'
    STATE_FINALIZED = 'FINALIZED'
    STATE_CHOICES = [
        (STATE_OPEN, 'Open'),
        (STATE_LOCKED, 'Locked — Pending Review'),
        (STATE_FINALIZED, 'Finalized'),
    ]

    year = models.PositiveIntegerField(unique=True)
    scheduled_closing_date = models.DateField()
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=STATE_OPEN)
    cutoff_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='locked_financial_years',
    )
    auto_locked = models.BooleanField(default=False)
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='finalized_financial_years',
    )
    current_version = models.PositiveIntegerField(default=0)
    needs_regeneration = models.BooleanField(default=False)
    last_correction_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year']


class SettlementVersion(models.Model):
    financial_year = models.ForeignKey(
        FinancialYearClose, on_delete=models.PROTECT, related_name='versions'
    )
    version = models.PositiveIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_settlement_versions',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    cutoff_at = models.DateTimeField()
    total_savings = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    collected_interest_pool = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_payout = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_group_loss = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        ordering = ['-version']
        constraints = [
            models.UniqueConstraint(
                fields=['financial_year', 'version'],
                name='unique_financial_year_settlement_version',
            ),
        ]


class AccountSettlement(models.Model):
    STATUS_UNPAID = 'UNPAID'
    STATUS_PARTIAL = 'PARTIAL'
    STATUS_PAID = 'PAID'
    STATUS_CHOICES = [
        (STATUS_UNPAID, 'Unpaid'),
        (STATUS_PARTIAL, 'Partially Paid'),
        (STATUS_PAID, 'Paid'),
    ]

    settlement_version = models.ForeignKey(
        SettlementVersion, on_delete=models.PROTECT, related_name='account_settlements'
    )
    account = models.ForeignKey(
        SavingsAccount, on_delete=models.PROTECT, related_name='settlements'
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='account_settlements',
    )
    savings_total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    interest_share = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    welfare_due = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    fine_due = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    annual_due = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    borrower_loan_offset = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    guarantor_offset = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    gross_payout = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    net_payout = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    payout_status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_UNPAID
    )

    class Meta:
        ordering = ['member__first_name', 'member__last_name', 'account__label']
        constraints = [
            models.UniqueConstraint(
                fields=['settlement_version', 'account'],
                name='unique_account_per_settlement_version',
            ),
        ]

    @property
    def outstanding_payout(self):
        return max(self.net_payout - self.amount_paid, Decimal('0.00'))


class SettlementPayoutPayment(models.Model):
    account_settlement = models.ForeignKey(
        AccountSettlement, on_delete=models.PROTECT, related_name='payments'
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    paid_on = models.DateField()
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='recorded_settlement_payouts',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['paid_on', 'id']


class FinancialYearLoanSnapshot(models.Model):
    financial_year = models.ForeignKey(
        FinancialYearClose, on_delete=models.PROTECT, related_name='loan_snapshots'
    )
    loan = models.ForeignKey(
        'loans.LoanRequest', on_delete=models.PROTECT, related_name='year_end_snapshots'
    )
    frozen_balance = models.DecimalField(max_digits=16, decimal_places=2)
    collected_interest = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    frozen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['financial_year', 'loan'],
                name='unique_financial_year_loan_snapshot',
            ),
        ]


class SettlementLoanAllocation(models.Model):
    TYPE_BORROWER = 'BORROWER'
    TYPE_GUARANTOR = 'GUARANTOR'
    TYPE_GROUP_LOSS = 'GROUP_LOSS'
    TYPE_CHOICES = [
        (TYPE_BORROWER, 'Borrower payout offset'),
        (TYPE_GUARANTOR, 'Guarantor payout offset'),
        (TYPE_GROUP_LOSS, 'Group loss'),
    ]

    settlement_version = models.ForeignKey(
        SettlementVersion, on_delete=models.PROTECT, related_name='loan_allocations'
    )
    loan_snapshot = models.ForeignKey(
        FinancialYearLoanSnapshot, on_delete=models.PROTECT, related_name='allocations'
    )
    allocation_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='settlement_loan_allocations',
    )
    account = models.ForeignKey(
        SavingsAccount, on_delete=models.PROTECT,
        null=True, blank=True, related_name='settlement_loan_allocations',
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['loan_snapshot_id', 'id']
