from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.core.paginator import Paginator

from deposits.models import DepositSubmission
from groupcore.reporting import merge_year_options, parse_report_year, years_from_dates

from .models import ShareContribution, AnnualSubscription
from .forms import ShareContributionForm, AnnualSubscriptionForm

# Create your views here.

@login_required
def income_list(request):
    if not (request.user.is_treasurer() or request.user.is_chairman()):
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    selected_year = parse_report_year(request.GET.get('year'))
    approved_deposits_base = DepositSubmission.objects.filter(status='APPROVED')
    years = merge_year_options(
        years_from_dates(approved_deposits_base, 'payment_week'),
        years_from_dates(ShareContribution.objects.all(), 'contribution_date'),
        AnnualSubscription.objects.values_list('year', flat=True).distinct(),
        selected_year=selected_year,
    )

    financial_deposits = (
        approved_deposits_base
        .filter(payment_week__year=selected_year)
        .select_related('member', 'account', 'submitted_by')
        .order_by('-payment_week', 'member__username', 'account__label', '-id')
    )
    raw_totals = financial_deposits.aggregate(
        total=Sum('amount'),
        saving=Sum('saving_amount'),
        welfare=Sum('welfare_amount'),
        annual=Sum('annual_subscription_amount'),
        membership=Sum('membership_amount'),
        fine=Sum('fine_amount'),
        shares=Sum('shares_amount'),
        loan_repayment=Sum('loan_repayment_amount'),
    )
    summary_totals = {key: value or 0 for key, value in raw_totals.items()}
    summary_totals['record_count'] = financial_deposits.count()
    financial_deposits = Paginator(financial_deposits, 10).get_page(request.GET.get('page'))

    shares = (
        ShareContribution.objects
        .select_related('member', 'account', 'recorded_by')
        .filter(contribution_date__year=selected_year)
        .order_by('-contribution_date')
    )
    subscriptions = (
        AnnualSubscription.objects
        .select_related('member', 'recorded_by')
        .filter(year=selected_year)
        .order_by('-year', 'member__username')
    )
    return render(request, 'incomes/income_list.html', {
        'financial_deposits': financial_deposits,
        'selected_year': selected_year,
        'years': years,
        'summary_totals': summary_totals,
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
