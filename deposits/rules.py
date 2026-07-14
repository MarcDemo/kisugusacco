from decimal import Decimal

from django.db.models import Sum


MIN_WEEKLY_SAVINGS = Decimal('10000.00')
MAX_WEEKLY_SAVINGS = Decimal('50000.00')


def weekly_savings_total(member, account, payment_week, statuses=('APPROVED',)):
    from .models import DepositSubmission

    queryset = DepositSubmission.objects.filter(
        member=member,
        account=account,
        payment_week=payment_week,
        status__in=statuses,
        saving_amount__gt=0,
    )
    return queryset.aggregate(total=Sum('saving_amount'))['total'] or Decimal('0.00')


def weekly_savings_paid(member, account, payment_week):
    return weekly_savings_total(member, account, payment_week) >= MIN_WEEKLY_SAVINGS
