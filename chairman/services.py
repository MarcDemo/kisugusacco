from django.core.exceptions import ValidationError
from django.db import transaction

from deposits.models import DepositSubmission
from fines.models import Fine
from groupcore.models import (
    AccountSettlement,
    MemberProfile,
    SavingsAccount,
    SavingsAccountOwnershipTransfer,
    SettlementLoanAllocation,
)
from incomes.models import ShareContribution
from loans.models import LoanRequest


@transaction.atomic
def make_account_dependent(*, account_id, target_member_id, transferred_by, reason):
    reason = ' '.join((reason or '').split())
    if len(reason) < 5:
        raise ValidationError('Give a clear transfer reason of at least 5 characters.')

    account = (
        SavingsAccount.objects.select_for_update()
        .select_related('owner')
        .get(pk=account_id)
    )
    old_owner = MemberProfile.objects.select_for_update().get(pk=account.owner_id)
    new_owner = MemberProfile.objects.select_for_update().get(pk=target_member_id)

    if old_owner.is_superuser:
        raise ValidationError(
            'A superuser savings account cannot be made dependent.'
        )
    source_account_count = (
        SavingsAccount.objects.select_for_update().filter(owner=old_owner).count()
    )
    if source_account_count < 1:
        raise ValidationError('This account no longer belongs to the source member.')
    if new_owner.pk == old_owner.pk:
        raise ValidationError('Select a different member to receive this account.')
    if not new_owner.is_active or new_owner.is_superuser:
        raise ValidationError('The receiving member must be an active non-superuser account.')
    if SavingsAccount.objects.filter(
        owner=new_owner,
        label__iexact=account.label,
    ).exclude(pk=account.pk).exists():
        raise ValidationError(
            f'{new_owner} already has a savings account named "{account.label}".'
        )

    source_profile_deactivated = (
        source_account_count == 1
        and old_owner.role == 'MEMBER'
        and old_owner.is_active
    )
    account.owner = new_owner
    account.save(update_fields=['owner'])

    DepositSubmission.objects.filter(account=account).update(member=new_owner)
    Fine.objects.filter(account=account).update(member=new_owner)
    ShareContribution.objects.filter(account=account).update(member=new_owner)
    LoanRequest.objects.filter(account=account).update(member=new_owner)
    AccountSettlement.objects.filter(account=account).update(member=new_owner)
    SettlementLoanAllocation.objects.filter(account=account).update(member=new_owner)

    if source_profile_deactivated:
        old_owner.is_active = False
        old_owner.save(update_fields=['is_active'])

    transfer = SavingsAccountOwnershipTransfer.objects.create(
        account=account,
        old_owner=old_owner,
        new_owner=new_owner,
        transferred_by=transferred_by,
        account_label=account.label,
        reason=reason,
        source_profile_deactivated=source_profile_deactivated,
    )
    return account, transfer
