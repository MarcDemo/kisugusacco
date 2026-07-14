from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from deposits.models import DepositSubmission
from deposits.rules import MIN_WEEKLY_SAVINGS
from fines.models import Fine
from groupcore.models import GroupSettings
from groupcore.week_cycle import current_saving_week


WEEKLY_SAVINGS_AMOUNT = MIN_WEEKLY_SAVINGS
LATE_FINE_AMOUNT = Decimal('1000.00')


def week_deadline(friday):
    """Return Sunday 23:59:59 in the configured (Kampala) timezone."""
    local_tz = timezone.get_current_timezone()
    return timezone.make_aware(
        datetime.combine(friday + timedelta(days=2), time.max),
        local_tz,
    )


def cycle_weeks(week_one_start, today=None):
    today = today or timezone.localdate()
    active = current_saving_week(week_one_start, today)
    next_cycle = current_saving_week(week_one_start, date(today.year + 1, 7, 1)).cycle_start
    count = max(((next_cycle - active.cycle_start).days // 7), active.week_number)
    return active, [active.cycle_start + timedelta(weeks=index) for index in range(count)]


def _completion_for_week(member, account, friday):
    deposits = (
        DepositSubmission.objects.filter(
            member=member,
            account=account,
            status='APPROVED',
            payment_week=friday,
            saving_amount__gt=0,
        )
        .order_by('payment_date', 'payment_time', 'id')
    )
    paid = Decimal('0')
    completed_at = None
    for deposit in deposits:
        paid += deposit.saving_amount
        if completed_at is None and paid >= WEEKLY_SAVINGS_AMOUNT:
            completed_at = timezone.make_aware(
                datetime.combine(deposit.payment_date, deposit.payment_time),
                timezone.get_current_timezone(),
            )
    return paid, completed_at


def ensure_overdue_fines(member=None, account=None, now=None):
    """Idempotently create fines for every account/week unpaid at its deadline."""
    now = now or timezone.now()
    group_settings = GroupSettings.get_active()
    if not group_settings:
        return 0

    accounts = account.__class__.objects.filter(is_active=True, owner__is_superuser=False) if account else None
    if accounts is None:
        from groupcore.models import SavingsAccount
        accounts = SavingsAccount.objects.filter(is_active=True, owner__is_superuser=False)
    if member:
        accounts = accounts.filter(owner=member)
    if account:
        accounts = accounts.filter(pk=account.pk)

    created = 0
    _active, weeks = cycle_weeks(group_settings.week_one_start, timezone.localdate(now))
    for savings_account in accounts.select_related('owner'):
        for friday in weeks:
            deadline = week_deadline(friday)
            if deadline >= now:
                break
            _paid, completed_at = _completion_for_week(savings_account.owner, savings_account, friday)
            if completed_at and completed_at <= deadline:
                continue
            _fine, was_created = Fine.objects.get_or_create(
                member=savings_account.owner,
                account=savings_account,
                fine_type='MISSED_WEEKLY_SAVING',
                reference_week=friday,
                defaults={
                    'reason': f'Late weekly saving - Week closing {friday:%d %b %Y}',
                    'amount': LATE_FINE_AMOUNT,
                    'issued_by': None,
                },
            )
            created += int(was_created)
    return created


def build_weekly_calendar(member, account, today=None, create_fines=True):
    group_settings = GroupSettings.get_active()
    if not group_settings or not account:
        return {'cycle_open': False, 'weeks': [], 'summary': {}}

    today = today or timezone.localdate()
    now = timezone.now()
    if create_fines:
        ensure_overdue_fines(member=member, account=account, now=now)
    active, weeks = cycle_weeks(group_settings.week_one_start, today)
    fines = {
        fine.reference_week: fine
        for fine in Fine.objects.filter(
            member=member,
            account=account,
            fine_type='MISSED_WEEKLY_SAVING',
            reference_week__in=weeks,
        )
    }

    cards = []
    for number, friday in enumerate(weeks, start=1):
        deadline = week_deadline(friday)
        paid, completed_at = _completion_for_week(member, account, friday)
        fully_paid = paid >= WEEKLY_SAVINGS_AMOUNT
        if fully_paid:
            status = 'paid_late' if completed_at > deadline else 'paid'
            label = 'Paid Late' if status == 'paid_late' else 'Paid on time'
        elif now > deadline:
            status, label = 'unpaid', 'Unpaid'
        else:
            status, label = 'future', 'Future'
        fine = fines.get(friday)
        cards.append({
            'number': number,
            'friday': friday,
            'deadline': deadline,
            'status': status,
            'status_label': label,
            'required': WEEKLY_SAVINGS_AMOUNT,
            'paid': paid,
            'remaining': max(WEEKLY_SAVINGS_AMOUNT - paid, Decimal('0')),
            'payment_date': completed_at,
            'fine': fine,
            'fine_outstanding': fine.outstanding_amount if fine else Decimal('0'),
            'is_current': number == active.week_number,
            'selectable': not fully_paid,
        })

    due_cards = [card for card in cards if card['deadline'] < now or card['is_current']]
    total_savings = DepositSubmission.objects.filter(
        member=member, account=account, status='APPROVED'
    ).aggregate(total=Sum('saving_amount'))['total'] or Decimal('0')
    return {
        'cycle_open': True,
        'saving_year': active.saving_year,
        'current_week_number': active.week_number,
        'weeks': cards,
        'summary': {
            'paid': sum(card['status'] in ('paid', 'paid_late') for card in cards),
            'behind': sum(card['status'] == 'unpaid' for card in cards),
            'paid_late': sum(card['status'] == 'paid_late' for card in cards),
            'outstanding': sum(card['remaining'] > 0 for card in due_cards),
            'outstanding_fines': sum((card['fine_outstanding'] for card in cards), Decimal('0')),
            'total_savings': total_savings,
        },
    }
