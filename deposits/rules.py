from collections import defaultdict
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum

from groupcore.week_cycle import current_saving_week


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


def weekly_savings_totals_by_week(
    member,
    account,
    payment_weeks=None,
    statuses=('APPROVED',),
):
    """Return approved savings totals keyed by week using one aggregate query."""
    from .models import DepositSubmission

    if not member:
        return {}

    queryset = DepositSubmission.objects.filter(
        member=member,
        account=account,
        status__in=statuses,
        saving_amount__gt=0,
    )
    if payment_weeks is not None:
        payment_weeks = tuple(payment_weeks)
        if not payment_weeks:
            return {}
        queryset = queryset.filter(payment_week__in=payment_weeks)

    return {
        row['payment_week']: row['total'] or Decimal('0.00')
        for row in queryset.values('payment_week').annotate(total=Sum('saving_amount'))
    }


def saving_week_statuses(member, account, payment_weeks, today=None, statuses=('APPROVED',)):
    """Return savings status and completion metadata for each configured week."""
    today = today or date.today()
    weeks = tuple(payment_weeks)
    if not member or not weeks:
        return {}

    from .models import DepositSubmission

    rows = (
        DepositSubmission.objects.filter(
            member=member,
            account=account,
            status__in=statuses,
            payment_week__in=weeks,
            saving_amount__gt=0,
        )
        .values('payment_week', 'saving_amount', 'payment_date', 'payment_time', 'id')
        .order_by('payment_week', 'payment_date', 'payment_time', 'id')
    )
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['payment_week']].append(row)

    result = {}
    for week in weeks:
        total = Decimal('0.00')
        completion_date = None
        for row in grouped.get(week, []):
            total += row['saving_amount'] or Decimal('0.00')
            if completion_date is None and total >= MIN_WEEKLY_SAVINGS:
                completion_date = row['payment_date']
        deadline = week + timedelta(days=2)
        if total >= MIN_WEEKLY_SAVINGS:
            status = 'paid_late' if completion_date and completion_date > deadline else 'paid_on_time'
        elif week > today:
            status = 'upcoming'
        elif today > deadline:
            status = 'missed'
        else:
            status = 'available'
        result[week] = {
            'status': status,
            'total': total,
            'completion_date': completion_date,
            'deadline': deadline,
            'selectable': total < MIN_WEEKLY_SAVINGS,
        }
    return result


def fine_week_options(member, account, payment_weeks=None):
    """Return fine state grouped by week, including all account fallbacks."""
    from fines.models import Fine

    queryset = Fine.objects.filter(member=member, fine_type='MISSED_WEEKLY_SAVING')
    if account is not None:
        queryset = queryset.filter(Q(account=account) | Q(account__isnull=True))
    else:
        queryset = queryset.filter(account__isnull=True)
    if payment_weeks is not None:
        weeks = tuple(payment_weeks)
        if not weeks:
            return {}
        queryset = queryset.filter(reference_week__in=weeks)

    grouped = defaultdict(lambda: {
        'fine_ids': [],
        'outstanding_ids': [],
        'fine_allocations': [],
        'outstanding': Decimal('0.00'),
        'has_fine': False,
    })
    for fine in queryset.order_by('reference_week', 'id'):
        if not fine.reference_week:
            continue
        outstanding = max((fine.amount or Decimal('0.00')) - (fine.amount_paid or Decimal('0.00')), Decimal('0.00'))
        item = grouped[fine.reference_week]
        item['has_fine'] = True
        item['fine_ids'].append(fine.id)
        if outstanding > 0:
            item['outstanding_ids'].append(fine.id)
            item['fine_allocations'].append({
                'id': fine.id,
                'amount': outstanding,
            })
            item['outstanding'] += outstanding

    for item in grouped.values():
        if item['outstanding'] > 0:
            item['status'] = 'outstanding'
        elif item['has_fine']:
            item['status'] = 'paid'
        else:
            item['status'] = 'none'
        item['selectable'] = item['status'] == 'outstanding'
    return dict(grouped)


def saving_year_weeks(week_one_start, today=None):
    """Return every configured weekly start in the saving year containing today."""
    today = today or date.today()
    saving_week = current_saving_week(week_one_start, today)
    next_cycle = current_saving_week(
        week_one_start,
        date(saving_week.saving_year + 1, 1, 1),
    )
    week_count = (next_cycle.cycle_start - saving_week.cycle_start).days // 7
    weeks = [
        saving_week.cycle_start + timedelta(weeks=index)
        for index in range(week_count)
    ]
    return saving_week, weeks


def weekly_savings_paid(member, account, payment_week):
    return weekly_savings_total(member, account, payment_week) >= MIN_WEEKLY_SAVINGS
