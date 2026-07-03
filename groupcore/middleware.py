from django.shortcuts import redirect
from django.urls import reverse

from .account_context import SESSION_KEY_ACTIVE_ACCOUNT, get_user_active_accounts


class RequireActiveSavingsAccountMiddleware:
    """Force member users with multiple active accounts to select one account context first."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        if not request.user.is_member():
            return self.get_response(request)

        exempt_paths = {
            reverse('select_savings_account'),
            reverse('logout'),
            reverse('login'),
        }

        path = request.path
        if path in exempt_paths or path.startswith('/admin/') or path.startswith('/media/'):
            return self.get_response(request)

        accounts = get_user_active_accounts(request.user)
        if accounts.count() <= 1:
            only_account = accounts.first()
            if only_account:
                request.session[SESSION_KEY_ACTIVE_ACCOUNT] = only_account.id
            return self.get_response(request)

        active_id = request.session.get(SESSION_KEY_ACTIVE_ACCOUNT)
        if not active_id or not accounts.filter(id=active_id).exists():
            return redirect('select_savings_account')

        return self.get_response(request)