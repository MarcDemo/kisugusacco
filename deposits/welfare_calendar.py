from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from deposits.models import DepositWelfareAllocation
from deposits.rules import saving_year_weeks
from groupcore.models import GroupSettings
from groupcore.savings_calendar import week_deadline
from groupcore.week_cycle import saving_year_closing_date


WEEKLY_WELFARE_AMOUNT = Decimal('1000.00')


def welfare_totals_by_week(
    member,
    account,
    weeks,
    statuses=('PENDING', 'APPROVED'),
    exclude_deposit_ids=None,
):
    totals = {}
    if not member or not account or not weeks:
        return totals
    queryset = DepositWelfareAllocation.objects.filter(
            deposit__member=member,
            account=account,
            welfare_week__in=weeks,
            deposit__status__in=statuses,
        )
    if exclude_deposit_ids:
        queryset = queryset.exclude(deposit_id__in=exclude_deposit_ids)
    rows = (
        queryset
        .values('welfare_week', 'deposit__status')
        .annotate(total=Sum('amount'))
    )
    for row in rows:
        state = totals.setdefault(
            row['welfare_week'],
            {'approved': Decimal('0.00'), 'pending': Decimal('0.00')},
        )
        state[row['deposit__status'].lower()] = row['total'] or Decimal('0.00')
    return totals


def build_welfare_calendar(member, account, today=None, exclude_deposit_ids=None):
    settings = GroupSettings.get_active()
    if not settings or not member or not account:
        return {'cycle_open': False, 'weeks': [], 'summary': {}}

    today = today or timezone.localdate()
    active, weeks = saving_year_weeks(settings.week_one_start, today)
    totals = welfare_totals_by_week(
        member,
        account,
        weeks,
        exclude_deposit_ids=exclude_deposit_ids,
    )
    now = timezone.now()
    cards = []
    for number, friday in enumerate(weeks, start=1):
        amounts = totals.get(friday, {})
        approved = amounts.get('approved', Decimal('0.00'))
        pending = amounts.get('pending', Decimal('0.00'))
        deadline = week_deadline(friday)
        if approved >= WEEKLY_WELFARE_AMOUNT:
            status, label = 'paid', 'Paid'
        elif pending >= WEEKLY_WELFARE_AMOUNT:
            status, label = 'pending', 'Pending approval'
        elif now > deadline:
            status, label = 'missed', 'Missed'
        elif friday <= today < friday + timedelta(days=7):
            status, label = 'current', 'Current'
        else:
            status, label = 'future', 'Future'
        cards.append({
            'number': number,
            'friday': friday,
            'deadline': deadline,
            'status': status,
            'status_label': label,
            'amount': WEEKLY_WELFARE_AMOUNT,
            'selectable': status in ('missed', 'current', 'future'),
            'is_current': status == 'current',
        })

    due_cards = [card for card in cards if card['deadline'] < now or card['is_current']]
    outstanding = sum(
        (WEEKLY_WELFARE_AMOUNT for card in due_cards if card['status'] != 'paid'),
        Decimal('0.00'),
    )
    month_groups = []
    for card in cards:
        month_key = (card['friday'].year, card['friday'].month)
        if not month_groups or month_groups[-1]['key'] != month_key:
            month_groups.append({
                'key': month_key,
                'label': card['friday'].strftime('%B %Y'),
                'weeks': [],
            })
        month_groups[-1]['weeks'].append(card)
    return {
        'cycle_open': True,
        'saving_year': active.saving_year,
        'closing_date': saving_year_closing_date(active.saving_year),
        'weeks': cards,
        'month_groups': month_groups,
        'summary': {
            'paid': sum(card['status'] == 'paid' for card in cards),
            'pending': sum(card['status'] == 'pending' for card in cards),
            'missed': sum(card['status'] == 'missed' for card in cards),
            'outstanding': outstanding,
        },
    }
