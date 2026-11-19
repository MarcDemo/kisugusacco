from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from groupcore.models import SavingsAccount

from .forms import WithdrawalForm
from .models import Withdrawal
from .services import account_balance, create_withdrawal, edit_withdrawal, void_withdrawal


def _treasurer_only(request):
    if not request.user.is_treasurer():
        messages.error(request, 'Only the Treasurer can manage withdrawals.')
        return redirect('member_dashboard')
    return None


def _apply_errors(form, exc):
    if hasattr(exc, 'message_dict'):
        for field, errors in exc.message_dict.items():
            target = field if field in form.fields else None
            for error in errors:
                form.add_error(target, error)
    else:
        for error in getattr(exc, 'messages', [str(exc)]):
            form.add_error(None, error)


@login_required
def withdrawal_list(request):
    denied = _treasurer_only(request)
    if denied:
        return denied
    query = request.GET.get('q', '').strip()
    records = Withdrawal.objects.select_related('member', 'account', 'recorded_by', 'voided_by')
    if query:
        records = records.filter(
            Q(member__username__icontains=query)
            | Q(member__first_name__icontains=query)
            | Q(member__last_name__icontains=query)
            | Q(account__label__icontains=query)
            | Q(reference__icontains=query)
        )
    return render(request, 'withdrawals/list.html', {'withdrawals': records, 'query': query})


@login_required
def withdrawal_create(request):
    denied = _treasurer_only(request)
    if denied:
        return denied
    initial = {}
    account = SavingsAccount.objects.filter(pk=request.GET.get('account'), is_active=True).select_related('owner').first()
    if account:
        initial = {'member': account.owner_id, 'account': account.pk}
    form = WithdrawalForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            item = create_withdrawal(data=form.cleaned_data, user=request.user)
        except ValidationError as exc:
            _apply_errors(form, exc)
        else:
            messages.success(request, 'Withdrawal recorded and the member has been notified.')
            return redirect('withdrawal_detail', withdrawal_id=item.pk)
    return render(request, 'withdrawals/form.html', {'form': form, 'title': 'Record withdrawal'})


@login_required
def withdrawal_edit(request, withdrawal_id):
    denied = _treasurer_only(request)
    if denied:
        return denied
    item = get_object_or_404(Withdrawal.objects.select_related('member', 'account'), pk=withdrawal_id)
    form = WithdrawalForm(
        request.POST or None,
        instance=item,
        require_correction_reason=True,
    )
    if request.method == 'POST' and form.is_valid():
        try:
            edit_withdrawal(
                withdrawal_id=item.pk,
                data=form.cleaned_data,
                user=request.user,
                correction_reason=form.cleaned_data['correction_reason'],
            )
        except ValidationError as exc:
            _apply_errors(form, exc)
        else:
            messages.success(request, 'Withdrawal corrected. The original values remain in the audit history.')
            return redirect('withdrawal_detail', withdrawal_id=item.pk)
    return render(request, 'withdrawals/form.html', {
        'form': form, 'title': 'Edit withdrawal', 'withdrawal': item,
    })


@login_required
def withdrawal_detail(request, withdrawal_id):
    denied = _treasurer_only(request)
    if denied:
        return denied
    item = get_object_or_404(
        Withdrawal.objects.select_related('member', 'account', 'recorded_by', 'voided_by').prefetch_related('revisions__edited_by'),
        pk=withdrawal_id,
    )
    return render(request, 'withdrawals/detail.html', {'withdrawal': item})


@login_required
def withdrawal_void(request, withdrawal_id):
    denied = _treasurer_only(request)
    if denied:
        return denied
    if request.method != 'POST':
        return redirect('withdrawal_detail', withdrawal_id=withdrawal_id)
    try:
        void_withdrawal(
            withdrawal_id=withdrawal_id,
            user=request.user,
            reason=request.POST.get('void_reason'),
        )
    except ValidationError as exc:
        messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
    else:
        messages.success(request, 'Withdrawal voided. Its audit history has been retained.')
    return redirect('withdrawal_detail', withdrawal_id=withdrawal_id)


@login_required
def withdrawal_balance(request):
    if not request.user.is_treasurer():
        return JsonResponse({'error': 'Forbidden'}, status=403)
    account = get_object_or_404(SavingsAccount, pk=request.GET.get('account'), is_active=True)
    balance = account_balance(account, as_of=timezone.localdate())
    return JsonResponse({key: str(value) for key, value in balance.items()})

