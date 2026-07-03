from messaging.models import Message, MessageRecipient
from groupcore.account_context import get_active_account, get_user_active_accounts

def unread_messages_count(request):
    if request.user.is_authenticated:
        count = MessageRecipient.objects.filter(recipient=request.user, is_read=False).count()
        return {'unread_count': count}
    return {}


def active_savings_account_context(request):
    if not request.user.is_authenticated:
        return {
            'active_savings_account': None,
            'available_savings_accounts': [],
            'has_multiple_savings_accounts': False,
        }

    available_accounts = list(get_user_active_accounts(request.user))
    active_account = get_active_account(request, request.user)

    return {
        'active_savings_account': active_account,
        'available_savings_accounts': available_accounts,
        'has_multiple_savings_accounts': len(available_accounts) > 1,
    }
