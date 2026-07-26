from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.core.paginator import Paginator
from django.utils import timezone

from deposits.models import DepositSubmission
from groupcore.member_query import alphabetical_members
from groupcore.models import MemberProfile
from groupcore.reporting import (
    merge_year_options,
    parse_report_year,
    years_from_dates,
)
from groupcore.year_close import submissions_locked_for_year

from .models import ShareContribution, AnnualSubscription
from .forms import ShareContributionForm, AnnualSubscriptionForm

# Create your views here.

@login_required
def income_list(request):
    if not (request.user.is_treasurer() or request.user.is_chairman()):
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    selected_year = parse_report_year(request.GET.get('year'))
    selected_member = None
    try:
        selected_member_id = int(request.GET.get('member', ''))
    except (TypeError, ValueError):
        selected_member_id = None
    if selected_member_id:
        selected_member = MemberProfile.objects.filter(
            pk=selected_member_id,
            is_superuser=False,
        ).first()

    members = alphabetical_members(
        MemberProfile.objects.filter(is_superuser=False)
    )
    approved_deposits_base = DepositSubmission.objects.filter(
        status='APPROVED',
        member__is_superuser=False,
    )
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
    if selected_member:
        financial_deposits = financial_deposits.filter(member=selected_member)
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
    if selected_member:
        shares = shares.filter(member=selected_member)
        subscriptions = subscriptions.filter(member=selected_member)
    active_filters = request.GET.copy()
    active_filters.pop('page', None)
    active_filters['year'] = selected_year
    if selected_member:
        active_filters['member'] = selected_member.id
    else:
        active_filters.pop('member', None)
    return render(request, 'incomes/income_list.html', {
        'financial_deposits': financial_deposits,
        'selected_year': selected_year,
        'selected_member': selected_member,
        'members': members,
        'years': years,
        'summary_totals': summary_totals,
        'shares': shares,
        'subscriptions': subscriptions,
        'pagination_query': active_filters.urlencode(),
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
            if submissions_locked_for_year(timezone.localdate().year):
                messages.error(request, 'The current financial year is locked.')
                return redirect('other_income_list')
            share = share_form.save(commit=False)
            share.recorded_by = request.user
            share.full_clean()
            share.save()
            messages.success(request, "Share contribution recorded successfully.")
            return redirect('other_income_list')

        if 'save_subscription' in request.POST and subscription_form.is_valid():
            subscription = subscription_form.save(commit=False)
            if submissions_locked_for_year(subscription.year):
                messages.error(
                    request,
                    f'The {subscription.year} financial year is locked.',
                )
                return redirect('other_income_list')
            subscription.recorded_by = request.user
            subscription.save()
            messages.success(request, "Annual subscription recorded successfully.")
            return redirect('other_income_list')

    return render(request, 'incomes/add_income.html', {
        'share_form': share_form,
        'subscription_form': subscription_form,
    })
