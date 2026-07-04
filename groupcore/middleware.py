from urllib.parse import quote

from django.http import HttpResponseRedirect
from django.urls import reverse

from .account_context import SESSION_KEY_ACTIVE_ACCOUNT, get_user_active_accounts


class RequireActiveSavingsAccountMiddleware:
    """Force account selection before member-facing features use account-scoped data."""

    MEMBER_ACCOUNT_PATH_NAMES = [
        'member_dashboard',
        'submit_deposit',
        'my_contributions',
        'my_fines',
        'my_loans',
        'request_loan',
    ]
    MEMBER_ACCOUNT_PATH_PREFIX_NAMES = [
        'export_my_contributions',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        exempt_paths = {
            reverse('select_savings_account'),
            reverse('logout'),
            reverse('login'),
        }

        path = request.path
        if path in exempt_paths or path.startswith('/admin/') or path.startswith('/media/'):
            return self.get_response(request)

        protected_paths = {reverse(name) for name in self.MEMBER_ACCOUNT_PATH_NAMES}
        protected_prefixes = [
            reverse(name, args=['excel']).rsplit('excel/', 1)[0]
            for name in self.MEMBER_ACCOUNT_PATH_PREFIX_NAMES
        ]
        requires_account = (
            request.user.is_member()
            or path in protected_paths
            or any(path.startswith(prefix) for prefix in protected_prefixes)
        )
        if not requires_account:
            return self.get_response(request)

        accounts = get_user_active_accounts(request.user)
        if accounts.count() <= 1:
            only_account = accounts.first()
            if only_account:
                request.session[SESSION_KEY_ACTIVE_ACCOUNT] = only_account.id
            return self.get_response(request)

        active_id = request.session.get(SESSION_KEY_ACTIVE_ACCOUNT)
        if not active_id or not accounts.filter(id=active_id).exists():
            return HttpResponseRedirect(f"{reverse('select_savings_account')}?next={quote(request.get_full_path())}")

        return self.get_response(request)
