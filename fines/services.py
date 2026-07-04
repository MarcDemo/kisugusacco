from datetime import timedelta

from django.utils import timezone

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
    if deposit.status != 'APPROVED' or not deposit_was_paid_within_grace(deposit):
        return 0
    return delete_missed_saving_fines_covered(
        member=deposit.member,
        account=deposit.account,
        payment_week=deposit.payment_week,
    )
