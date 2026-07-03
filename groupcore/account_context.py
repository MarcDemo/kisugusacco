from django.shortcuts import get_object_or_404

from .models import SavingsAccount


SESSION_KEY_ACTIVE_ACCOUNT = 'active_account_id'


def get_user_active_accounts(user):
    if not user or not user.is_authenticated:
        return SavingsAccount.objects.none()
    return SavingsAccount.objects.filter(owner=user, is_active=True).order_by('label')


def get_active_account(request, user=None):
    user = user or getattr(request, 'user', None)
    accounts = get_user_active_accounts(user)
    if not user or not user.is_authenticated:
        return None

    active_id = request.session.get(SESSION_KEY_ACTIVE_ACCOUNT)
    if active_id:
        account = accounts.filter(id=active_id).first()
        if account:
            return account

    only_account = accounts.first() if accounts.count() == 1 else None
    if only_account:
        request.session[SESSION_KEY_ACTIVE_ACCOUNT] = only_account.id
        return only_account

    return None


def set_active_account(request, account_id):
    account = get_object_or_404(
        SavingsAccount,
        id=account_id,
        owner=request.user,
        is_active=True,
    )
    request.session[SESSION_KEY_ACTIVE_ACCOUNT] = account.id
    return account