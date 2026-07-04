from django.shortcuts import render, redirect, get_object_or_404
from .models import Fine
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from .forms import FineForm
from groupcore.account_context import get_active_account

# Create your views here.
@login_required
def my_fines(request):
    active_account = get_active_account(request, request.user)
    fines = Fine.objects.filter(member=request.user).order_by('-date_issued')
    if active_account:
        fines = fines.filter(account=active_account)
    total_fines = fines.aggregate(Sum('amount'))['amount__sum'] or 0
    stats = fines.aggregate(
        paid_count=Count('id', filter=Q(is_paid=True)),
        unpaid_count=Count('id', filter=Q(is_paid=False)),
        outstanding_amount=Sum('amount', filter=Q(is_paid=False)),
    )
    return render(request, 'fines/my_fines.html', {
        'fines': fines,
        'total_fines': total_fines,
        'stats': stats,
        'active_account': active_account,
    })

@login_required
def manage_fines(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    fines = Fine.objects.select_related('member', 'account').order_by('-date_issued')
    totals = fines.aggregate(
        total_records=Count('id'),
        paid_count=Count('id', filter=Q(is_paid=True)),
        unpaid_count=Count('id', filter=Q(is_paid=False)),
        total_amount=Sum('amount'),
        unpaid_amount=Sum('amount', filter=Q(is_paid=False)),
    )
    return render(request, 'fines/manage_fines.html', {
        'fines': fines,
        'totals': totals,
    })


@login_required
def add_fine(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    if request.method == 'POST':
        form = FineForm(request.POST)
        if form.is_valid():
            fine = form.save(commit=False)
            fine.issued_by = request.user
            fine.full_clean()
            fine.save()
            messages.success(request, f"Fine added for {fine.member.username}.")
            return redirect('manage_fines')
    else:
        form = FineForm()

    return render(request, 'fines/add_fine.html', {'form': form})


@login_required
def mark_fine_paid(request, fine_id):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    fine = get_object_or_404(Fine, id=fine_id)
    fine.is_paid = True
    fine.full_clean()
    fine.save(update_fields=['is_paid'])

    messages.success(request, f"Marked fine for {fine.member.username} as paid.")
    return redirect('manage_fines')


@login_required
@require_POST
def delete_fine(request, fine_id):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    fine = get_object_or_404(Fine, id=fine_id)
    member_username = fine.member.username
    fine.delete()

    messages.success(request, f"Deleted fine for {member_username}.")
    return redirect('manage_fines')
