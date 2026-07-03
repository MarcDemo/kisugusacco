from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import ShareContribution, AnnualSubscription
from .forms import ShareContributionForm, AnnualSubscriptionForm

# Create your views here.

@login_required
def income_list(request):
    shares = ShareContribution.objects.select_related('member', 'account').order_by('-contribution_date')
    subscriptions = AnnualSubscription.objects.select_related('member').order_by('-year', 'member__username')
    return render(request, 'incomes/income_list.html', {
        'shares': shares,
        'subscriptions': subscriptions,
    })

@login_required
def add_income(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    share_form = ShareContributionForm(request.POST or None, prefix='share')
    subscription_form = AnnualSubscriptionForm(request.POST or None, prefix='subscription')

    if request.method == 'POST':
        if 'save_share' in request.POST and share_form.is_valid():
            share = share_form.save(commit=False)
            share.recorded_by = request.user
            share.full_clean()
            share.save()
            messages.success(request, "Share contribution recorded successfully.")
            return redirect('other_income_list')

        if 'save_subscription' in request.POST and subscription_form.is_valid():
            subscription = subscription_form.save(commit=False)
            subscription.recorded_by = request.user
            subscription.save()
            messages.success(request, "Annual subscription recorded successfully.")
            return redirect('other_income_list')

    return render(request, 'incomes/add_income.html', {
        'share_form': share_form,
        'subscription_form': subscription_form,
    })