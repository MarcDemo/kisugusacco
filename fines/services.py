from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django.db.models.deletion import ProtectedError
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

    cleared_count = 0
    for fine in fines:
        if fine.deposit_allocations.exists():
            cleared_count += int(fine.void(
                'Voided automatically because the weekly saving was completed on time. '
                'The fine is retained because a deposit allocation references it.'
            ))
        else:
            try:
                fine.delete()
                cleared_count += 1
            except ProtectedError:
                # An allocation may have been created after the existence check.
                fine.refresh_from_db()
                cleared_count += int(fine.void(
                    'Voided automatically because the weekly saving was completed on time. '
                    'The fine is retained because a deposit allocation references it.'
                ))
    return cleared_count


def delete_deposit_week_missed_saving_fines(deposit):
    from groupcore.savings_calendar import clear_on_time_missed_fine
    return clear_on_time_missed_fine(
        deposit.member,
        deposit.account,
        deposit.payment_week,
    )


def allocate_fine_payment(member, account, amount):
    """Apply a fine payment oldest-first and preserve partial balances."""
    remaining = amount
    applied = 0
    account_filter = Q(account=account)
    if account is not None:
        account_filter |= Q(account__isnull=True)
    fines = Fine.objects.filter(
        account_filter, member=member, is_paid=False, is_voided=False,
    ).order_by(
        'reference_week', 'date_issued', 'id'
    )
    for fine in fines:
        if remaining <= 0:
            break
        used = fine.apply_payment(remaining)
        applied += used
        remaining -= used
    return applied, remaining


def apply_selected_fine_allocations(allocations):
    """Apply persisted full-balance fine allocations atomically.

    ``allocations`` is an iterable of ``(fine, amount)`` pairs.  A selected
    fine must still have at least the recorded outstanding balance; otherwise
    the caller can safely reject the deposit instead of silently paying a
    different fine.
    """
    from django.core.exceptions import ValidationError
    from django.db import transaction

    allocations = list(allocations)
    with transaction.atomic():
        locked = []
        for fine, amount in allocations:
            fine = Fine.objects.select_for_update().get(pk=fine.pk)
            if fine.is_voided:
                week_label = (
                    f'{fine.reference_week:%d %b %Y}'
                    if fine.reference_week else f'#{fine.pk}'
                )
                raise ValidationError(
                    f'Fine {week_label} was voided before approval.'
                )
            outstanding = fine.outstanding_amount
            if outstanding < amount:
                week_label = (
                    f'{fine.reference_week:%d %b %Y}'
                    if fine.reference_week else f'#{fine.pk}'
                )
                raise ValidationError(
                    f'Fine {week_label} changed before approval.'
                )
            locked.append((fine, amount))
        for fine, amount in locked:
            fine.apply_payment(amount)
    return sum((amount for _fine, amount in locked), Decimal('0.00'))
