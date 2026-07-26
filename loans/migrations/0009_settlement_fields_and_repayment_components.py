from calendar import monthrange
from datetime import timedelta
from decimal import Decimal

from django.db import migrations, models


def add_months(base_date, months):
    year = base_date.year + (base_date.month - 1 + months) // 12
    month = (base_date.month - 1 + months) % 12 + 1
    return base_date.replace(
        year=year, month=month, day=min(base_date.day, monthrange(year, month)[1], 28)
    )


def elapsed_months(start, end):
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def accrued_interest(loan, repayments, as_of):
    anchor = (loan.approved_on or loan.requested_on).date()
    if as_of < anchor:
        return Decimal('0.00')
    rate = loan.monthly_interest_rate / Decimal('100.00')
    balance = Decimal(loan.principal)
    total_interest = Decimal('0.00')
    index = 0
    months = elapsed_months(anchor, as_of)
    for month_number in range(1, months + 2):
        if balance > 0 and rate > 0:
            charge = balance * rate
            balance += charge
            total_interest += charge
        month_end = add_months(anchor, month_number) if month_number <= months else as_of
        while index < len(repayments) and repayments[index].paid_on <= month_end:
            balance = max(balance - repayments[index].amount, Decimal('0.00'))
            index += 1
    return total_interest


def backfill_components(apps, schema_editor):
    LoanRequest = apps.get_model('loans', 'LoanRequest')
    for loan in LoanRequest.objects.all().iterator():
        prior = []
        interest_collected = Decimal('0.00')
        repayments = list(loan.repayments.order_by('paid_on', 'id'))
        for repayment in repayments:
            interest_due = max(
                accrued_interest(loan, prior, repayment.paid_on) - interest_collected,
                Decimal('0.00'),
            )
            repayment.interest_component = min(repayment.amount, interest_due)
            repayment.principal_component = repayment.amount - repayment.interest_component
            repayment.save(update_fields=['interest_component', 'principal_component'])
            interest_collected += repayment.interest_component
            prior.append(repayment)


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0008_loanrepayment_source_deposit'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequest',
            name='settlement_closed_on',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='settlement_loss',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='loanrepayment',
            name='interest_component',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='loanrepayment',
            name='principal_component',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AlterField(
            model_name='loanrequest',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING_GUARANTOR', 'Pending Guarantor Approval'),
                    ('PENDING', 'Pending Management Approval'),
                    ('APPROVED', 'Approved'),
                    ('REJECTED', 'Rejected'),
                    ('REJECTED_GUARANTOR', 'Rejected by Guarantor'),
                    ('SETTLED', 'Closed at Year-End Settlement'),
                ],
                default='PENDING',
                max_length=30,
            ),
        ),
        migrations.RunPython(backfill_components, migrations.RunPython.noop),
    ]
