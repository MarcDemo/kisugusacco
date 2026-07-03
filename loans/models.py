from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from groupcore.models import MemberProfile, SavingsAccount


class LoanRequest(models.Model):
    STATUS_PENDING_GUARANTOR = 'PENDING_GUARANTOR'
    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_REJECTED_GUARANTOR = 'REJECTED_GUARANTOR'

    STATUS_CHOICES = [
        (STATUS_PENDING_GUARANTOR, 'Pending Guarantor Approval'),
        (STATUS_PENDING, 'Pending Management Approval'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_REJECTED_GUARANTOR, 'Rejected by Guarantor'),
    ]

    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='loan_requests')
    account = models.ForeignKey(SavingsAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='loan_requests')
    principal = models.DecimalField(max_digits=12, decimal_places=2)
    monthly_interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('2.00'))
    duration_months = models.PositiveIntegerField(default=1)
    purpose = models.TextField(blank=True, null=True)

    treasurer_approved_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='treasurer_approved_loans')
    chairman_approved_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='chairman_approved_loans')
    vice_chairman_approved_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='vice_chairman_approved_loans')

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)
    requested_on = models.DateTimeField(auto_now_add=True)
    approved_on = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True, null=True)

    def clean(self):
        if self.principal <= 0:
            raise ValidationError({'principal': 'Loan amount must be greater than zero.'})
        if self.duration_months <= 0:
            raise ValidationError({'duration_months': 'Duration must be at least one month.'})
        if self.account_id and self.member_id and self.account.owner_id != self.member_id:
            raise ValidationError({'account': 'Selected account does not belong to this member.'})

    @property
    def monthly_repayment(self):
        """Reducing balance (EMI) formula: P * r / (1 - (1+r)^-n)"""
        r = self.monthly_interest_rate / Decimal('100.00')
        n = self.duration_months
        if r == 0 or n == 0:
            return self.principal / Decimal(n) if n else Decimal('0')
        factor = (1 + r) ** n
        return (self.principal * r * factor) / (factor - 1)

    @property
    def total_repayment(self):
        return self.monthly_repayment * Decimal(self.duration_months)

    @property
    def total_interest(self):
        return self.total_repayment - self.principal

    def _accrual_anchor_date(self):
        return self.approved_on.date() if self.approved_on else self.requested_on.date()

    def _monthly_rate_decimal(self):
        return self.monthly_interest_rate / Decimal('100.00')

    @staticmethod
    def _add_months(base_date, months):
        year = base_date.year + (base_date.month - 1 + months) // 12
        month = (base_date.month - 1 + months) % 12 + 1
        # Keep day in a safe range for all months.
        day = min(base_date.day, 28)
        return base_date.replace(year=year, month=month, day=day)

    @staticmethod
    def _elapsed_full_months(start_date, end_date):
        months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
        if end_date.day < start_date.day:
            months -= 1
        return max(months, 0)

    def amount_paid_as_of(self, as_of_date=None):
        as_of_date = as_of_date or timezone.now().date()
        total = Decimal('0.00')
        for repayment in self.repayments.all():
            if repayment.paid_on <= as_of_date:
                total += repayment.amount
        return total

    def _simulate_balance_as_of(self, as_of_date=None):
        """
        Simulate loan balance month-by-month with front-loaded interest.

        Rules:
        - Month 1 interest is charged IMMEDIATELY when the loan is given (at anchor date).
        - The moment we step into each subsequent month, that month's full interest is
          charged on the current outstanding balance before any further repayments.
        - Repayments made during a month reduce the balance available for the NEXT
          month's interest charge.
        - This continues beyond the agreed duration (extra/overdue months).
        """
        as_of_date = as_of_date or timezone.now().date()
        anchor = self._accrual_anchor_date()
        if as_of_date < anchor:
            return {
                'balance': self.principal,
                'paid': Decimal('0.00'),
                'interest': Decimal('0.00'),
                'months_elapsed': 0,
            }

        repayments = [r for r in self.repayments.all() if r.paid_on <= as_of_date]
        repayments.sort(key=lambda r: (r.paid_on, r.id))

        rate = self._monthly_rate_decimal()
        months_elapsed = self._elapsed_full_months(anchor, as_of_date)

        balance = Decimal(self.principal)
        total_paid = Decimal('0.00')
        total_interest = Decimal('0.00')
        repayment_index = 0

        # We have entered months 1 … (months_elapsed + 1).
        # Interest for month M is charged at the START of month M
        # (i.e. at anchor + (M-1) months).  Month 1 fires immediately at anchor.
        # Repayments made DURING month M (up to start of month M+1, or as_of_date
        # for the current partial month) reduce the balance before month M+1 fires.
        for month_number in range(1, months_elapsed + 2):
            # --- charge this month's interest on the current balance ---
            if balance > 0 and rate > 0:
                interest_for_month = balance * rate
                balance += interest_for_month
                total_interest += interest_for_month

            # --- apply repayments made during this month ---
            if month_number <= months_elapsed:
                # Full completed month: window ends at start of next month.
                month_end = self._add_months(anchor, month_number)
            else:
                # Current partial month: window ends at as_of_date.
                month_end = as_of_date

            while repayment_index < len(repayments) and repayments[repayment_index].paid_on <= month_end:
                repayment_amount = repayments[repayment_index].amount
                total_paid += repayment_amount
                balance -= repayment_amount
                if balance < 0:
                    balance = Decimal('0.00')
                repayment_index += 1

        return {
            'balance': balance,
            'paid': total_paid,
            'interest': total_interest,
            'months_elapsed': months_elapsed,
        }

    def overdue_months_as_of(self, as_of_date=None):
        if self.status != 'APPROVED':
            return 0
        as_of_date = as_of_date or timezone.now().date()
        months_elapsed = self._elapsed_full_months(self._accrual_anchor_date(), as_of_date)
        return max(months_elapsed - self.duration_months, 0)

    def overdue_interest_as_of(self, as_of_date=None):
        if self.status != 'APPROVED':
            return Decimal('0.00')

        as_of_date = as_of_date or timezone.now().date()
        overdue_months = self.overdue_months_as_of(as_of_date)
        if overdue_months <= 0:
            return Decimal('0.00')

        due_date = self._add_months(self._accrual_anchor_date(), self.duration_months)
        interest_at_due = self._simulate_balance_as_of(due_date)['interest']
        interest_now = self._simulate_balance_as_of(as_of_date)['interest']
        extra_interest = interest_now - interest_at_due
        return extra_interest if extra_interest > 0 else Decimal('0.00')

    def total_due_as_of(self, as_of_date=None):
        sim = self._simulate_balance_as_of(as_of_date)
        return sim['paid'] + sim['balance']

    def outstanding_balance_as_of(self, as_of_date=None):
        return self._simulate_balance_as_of(as_of_date)['balance']

    def repayment_status_as_of(self, as_of_date=None):
        if self.status != 'APPROVED':
            return None
        sim = self._simulate_balance_as_of(as_of_date)
        paid = sim['paid']
        outstanding = sim['balance']
        if outstanding <= 0:
            return 'FULLY_PAID'
        if paid <= 0:
            return 'UNPAID'
        return 'PROGRESS'

    @property
    def amount_paid(self):
        return self._simulate_balance_as_of()['paid']

    @property
    def outstanding_balance(self):
        return self.outstanding_balance_as_of()

    @property
    def repayment_progress_percent(self):
        total_due = self.total_due_as_of()
        if total_due <= 0:
            return Decimal('0.00')
        progress = (self.amount_paid / total_due) * Decimal('100.00')
        if progress < 0:
            return Decimal('0.00')
        if progress > 100:
            return Decimal('100.00')
        return progress

    @property
    def repayment_status(self):
        return self.repayment_status_as_of()

    @property
    def accrued_interest_as_of(self):
        return self._simulate_balance_as_of()['interest']

    @property
    def fully_approved(self):
        """Fully approved when Treasurer + (Chairman OR Vice Chairman) both approve"""
        treasurer_ok = bool(self.treasurer_approved_by)
        second_approval = bool(self.chairman_approved_by) or bool(self.vice_chairman_approved_by)
        return treasurer_ok and second_approval

    @property
    def awaiting_guarantors(self):
        return self.status == self.STATUS_PENDING_GUARANTOR

    @property
    def rejected_by_guarantor(self):
        return self.status == self.STATUS_REJECTED_GUARANTOR

    @property
    def guarantor_approval_count(self):
        if not self.pk:
            return 0
        return self.guarantor_approvals.filter(status=LoanGuarantorApproval.STATUS_APPROVED).count()

    @property
    def guarantor_pending_count(self):
        if not self.pk:
            return 0
        return self.guarantor_approvals.filter(status=LoanGuarantorApproval.STATUS_PENDING).count()

    @property
    def guarantor_rejection(self):
        if not self.pk:
            return None
        return self.guarantor_approvals.filter(
            status=LoanGuarantorApproval.STATUS_REJECTED
        ).select_related('guarantor').first()

    def guarantors_complete(self):
        if not self.pk:
            return False
        approvals = list(self.guarantor_approvals.all())
        return len(approvals) == 3 and all(
            approval.status == LoanGuarantorApproval.STATUS_APPROVED
            for approval in approvals
        )

    def mark_pending_if_guarantors_complete(self):
        if self.status == self.STATUS_PENDING_GUARANTOR and self.guarantors_complete():
            self.status = self.STATUS_PENDING
            self.save(update_fields=['status'])

    def mark_approved_if_complete(self):
        if self.fully_approved and self.status == self.STATUS_PENDING:
            self.status = self.STATUS_APPROVED
            self.approved_on = timezone.now()
            self.save(update_fields=['status', 'approved_on'])

    def __str__(self):
        member_name = self.member.username if self.member_id else "Unknown member"
        return f"Loan {self.id} - {member_name} - UGX {self.principal}"


class LoanGuarantorApproval(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    loan = models.ForeignKey(LoanRequest, on_delete=models.CASCADE, related_name='guarantor_approvals')
    guarantor = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='loan_guarantee_requests')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    comments = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('loan', 'guarantor')
        ordering = ['created_at', 'id']

    def approve(self, comments=''):
        self.status = self.STATUS_APPROVED
        self.comments = comments
        self.decided_at = timezone.now()

    def reject(self, comments=''):
        self.status = self.STATUS_REJECTED
        self.comments = comments
        self.decided_at = timezone.now()

    def __str__(self):
        return f"Loan {self.loan_id} guarantor {self.guarantor_id} - {self.status}"


class LoanRepayment(models.Model):
    loan = models.ForeignKey(LoanRequest, on_delete=models.CASCADE, related_name='repayments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField(default=timezone.now)
    recorded_by = models.ForeignKey(
        MemberProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recorded_loan_repayments',
    )
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_on', '-id']

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({'amount': 'Repayment amount must be greater than zero.'})
        if self.loan_id and self.loan.status != 'APPROVED':
            raise ValidationError({'loan': 'Repayments can only be recorded for approved loans.'})

    def __str__(self):
        return f"Repayment {self.id} - Loan {self.loan_id} - UGX {self.amount}"
