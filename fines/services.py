from .models import Fine


def mark_missed_saving_fines_covered(member, account, payment_week):
    if not member or not payment_week:
        return 0

    fines = Fine.objects.filter(
        member=member,
        fine_type='MISSED_WEEKLY_SAVING',
        reference_week=payment_week,
        is_paid=False,
    )
    if account:
        fines = fines.filter(account=account)
    else:
        fines = fines.filter(account__isnull=True)

    return fines.update(is_paid=True)


def mark_deposit_week_fines_covered(deposit):
    if deposit.status != 'APPROVED':
        return 0
    return mark_missed_saving_fines_covered(
        member=deposit.member,
        account=deposit.account,
        payment_week=deposit.payment_week,
    )
