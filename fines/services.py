from datetime import timedelta

from django.utils import timezone
from django.db.models import Q

from .models import Fine


def missed_saving_fines_can_be_created(week_closing_date, today=None):
    if not week_closing_date:
        return False
    today = today or timezone.localdate()
    return today > week_closing_date + timedelta(days=2)


def deposit_was_paid_within_grace(deposit):
    if not deposit.payment_week or not deposit.payment_date:
        return False
    return deposit.payment_date <= deposit.payment_week + timedelta(days=2)


def delete_missed_saving_fines_covered(member, account, payment_week):
    if not member or not payment_week:
        return 0

    fines = Fine.objects.filter(
        member=member,
        fine_type='MISSED_WEEKLY_SAVING',
        reference_week=payment_week,
    )
    if account:
        fines = fines.filter(account=account)
    else:
        fines = fines.filter(account__isnull=True)

    deleted_count, _deleted_by_model = fines.delete()
    return deleted_count


def delete_deposit_week_missed_saving_fines(deposit):
    # Kept as a compatibility shim. Late fines are independent financial
    # obligations and must never be deleted when savings are paid.
    return 0


def allocate_fine_payment(member, account, amount):
    """Apply a fine payment oldest-first and preserve partial balances."""
    remaining = amount
    applied = 0
    account_filter = Q(account=account)
    if account is not None:
        account_filter |= Q(account__isnull=True)
    fines = Fine.objects.filter(account_filter, member=member, is_paid=False).order_by(
        'reference_week', 'date_issued', 'id'
    )
    for fine in fines:
        if remaining <= 0:
            break
        used = fine.apply_payment(remaining)
        applied += used
        remaining -= used
    return applied, remaining
