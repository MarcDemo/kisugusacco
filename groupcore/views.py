from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import JsonResponse
from .models import MemberProfile
from .forms import GroupSettingsForm, MemberRegistrationForm
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from deposits.models import DepositSubmission
from django.utils import timezone
from fines.models import Fine
from django.db.models import Sum, Q
from incomes.models import ShareContribution, AnnualSubscription
from Assets_Expenditures.models import Expenditure, Asset
from documents.models import Document
from .forms import ProfileForm
from groupcore.models import GroupSettings
from groupcore.reporting import merge_year_options, parse_report_year, years_from_dates
from groupcore.week_cycle import current_saving_week, first_friday_of_year
from datetime import date
from loans.models import LoanRequest
from decimal import Decimal
import random
from django.core.mail import send_mail
import random, datetime
from django.core.mail import EmailMultiAlternatives
from groupcore.account_context import get_active_account, get_user_active_accounts, set_active_account


# Create your views here.
def _deposit_purpose_totals(queryset):
    totals = queryset.aggregate(
        saving=Sum('saving_amount'),
        welfare=Sum('welfare_amount'),
        annual_subscription=Sum('annual_subscription_amount'),
        fine=Sum('fine_amount'),
        shares=Sum('shares_amount'),
        total=Sum('amount'),
    )
    return {
        'saving': totals.get('saving') or Decimal('0'),
        'welfare': totals.get('welfare') or Decimal('0'),
        'annual_subscription': totals.get('annual_subscription') or Decimal('0'),
        'fine': totals.get('fine') or Decimal('0'),
        'shares': totals.get('shares') or Decimal('0'),
        'total': totals.get('total') or Decimal('0'),
    }


def _loan_interest_total(queryset):
    total = Decimal('0')
    for loan in queryset:
        total += Decimal(loan.total_interest or 0)
    return total


def _is_leadership(user):
    return user.is_chairman() or user.is_vice_chairman() or user.is_overseer()


def _can_manage_group_settings(user):
    return user.is_superuser or user.is_treasurer() or user.is_chairman()


FUND_SOURCE_TO_TOTAL_KEY = {
    'SAVINGS': 'saving',
    'WELFARE': 'welfare',
    'FINES': 'fine',
    'ANNUAL_SUBSCRIPTIONS': 'annual_subscription',
    'SHARES': 'shares',
}


def _fund_source_balances(queryset):
    purpose_totals = _deposit_purpose_totals(queryset)
    collected = {
        source: Decimal(purpose_totals[total_key] or 0)
        for source, total_key in FUND_SOURCE_TO_TOTAL_KEY.items()
    }

    expenditures = {
        source: Decimal(
            Expenditure.objects.filter(source=source).aggregate(total=Sum('amount'))['total'] or 0
        )
        for source in FUND_SOURCE_TO_TOTAL_KEY
    }
    assets = {
        source: Decimal(
            Asset.objects.filter(source=source).aggregate(total=Sum('value'))['total'] or 0
        )
        for source in FUND_SOURCE_TO_TOTAL_KEY
    }
    available = {
        source: collected[source] - expenditures[source] - assets[source]
        for source in FUND_SOURCE_TO_TOTAL_KEY
    }

    return {
        'collected': collected,
        'expenditures': expenditures,
        'assets': assets,
        'available': available,
    }


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            # Members with multiple active accounts must choose one context first.
            if user.is_member() and get_user_active_accounts(user).count() > 1:
                request.session.pop('active_account_id', None)
                return redirect('select_savings_account')

            if user.is_chairman():
                return redirect('chairman_dashboard')
            elif user.is_vice_chairman():
                return redirect('vice_chairman_dashboard')
            elif user.is_overseer():
                return redirect('overseer_dashboard')
            elif user.is_treasurer():
                return redirect('treasurer_dashboard')
            elif user.is_secretary():
                return redirect('secretary_dashboard')
            elif user.is_mobilizer():
                return redirect('mobilizer_dashboard')
            else:
                return redirect('member_dashboard')
        else:
            messages.error(request, "Invalid username or password")

    return render(request, 'groupcore/login.html')


@login_required
def select_savings_account(request):
    accounts = get_user_active_accounts(request.user)

    if accounts.count() == 0:
        messages.error(request, "No active savings account found. Please contact the treasurer.")
        return redirect('member_dashboard')

    if accounts.count() == 1:
        only_account = accounts.first()
        request.session['active_account_id'] = only_account.id
        return redirect('member_dashboard')

    if request.method == 'POST':
        account_id = request.POST.get('account_id')
        if not account_id:
            messages.error(request, "Please select an account.")
            return redirect('select_savings_account')
        set_active_account(request, account_id)
        messages.success(request, "Account context set successfully.")
        return redirect('member_dashboard')

    return render(request, 'groupcore/select_savings_account.html', {'accounts': accounts})


@login_required
def member_accounts_api(request, member_id):
    accounts = list(
        get_user_active_accounts(MemberProfile.objects.filter(id=member_id).first()).values('id', 'label')
    )
    return JsonResponse({'accounts': accounts})



RESET_CODE_EXPIRY_MINUTES = 10

def forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            member = MemberProfile.objects.get(email=email)  # assuming MemberProfile has an email field
            code = str(random.randint(100000, 999999))

            # Store reset info in session
            request.session['reset_email'] = email
            request.session['reset_code'] = code
            request.session['reset_expiry'] = (timezone.now() + datetime.timedelta(minutes=RESET_CODE_EXPIRY_MINUTES)).isoformat()

            # Email content
            subject = "Your Password Reset Code"
            text_content = f"Your password reset code is: {code}. This code will expire in {RESET_CODE_EXPIRY_MINUTES} minutes."
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; background-color:#f8f9fa; padding:20px;">
              <div style="max-width:600px; margin:auto; background:#ffffff; border-radius:8px; padding:20px; border:1px solid #ddd;">
                <h2 style="color:#0d6efd;">Password Reset Request</h2>
                <p>Hello {member.username},</p>
                <p>You requested to reset your password. Use the code below to proceed. This code will expire in <strong>{RESET_CODE_EXPIRY_MINUTES} minutes</strong>:</p>
                <div style="font-size:24px; font-weight:bold; letter-spacing:3px; background:#f1f1f1; padding:10px; border-radius:5px; text-align:center;">
                  {code}
                </div>
                <p>If you did not request this, please ignore this email.</p>
                <p style="color:#888; font-size:12px;">This is an automated message, please do not reply.</p>
              </div>
            </body>
            </html>
            """

            email_msg = EmailMultiAlternatives(subject, text_content, 'info.landinvestmentgroup@gmail.com', [email])
            email_msg.attach_alternative(html_content, "text/html")
            email_msg.send()

            messages.success(request, "A verification code has been sent to your email.")
            return redirect('verify_code')

        except MemberProfile.DoesNotExist:
            messages.error(request, "No account found with that email.")

    return render(request, 'groupcore/forgot_password.html')


def verify_code(request):
    if request.method == 'POST':
        entered_code = request.POST.get('code')
        saved_code = request.session.get('reset_code')
        expiry_str = request.session.get('reset_expiry')

        if not saved_code or not expiry_str:
            messages.error(request, "Your reset request has expired. Please try again.")
            return redirect('forgot_password')

        expiry_time = datetime.datetime.fromisoformat(expiry_str)

        if timezone.now() > expiry_time:
            request.session.pop('reset_code', None)
            request.session.pop('reset_expiry', None)
            messages.error(request, "The verification code has expired. Please request a new one.")
            return redirect('forgot_password')

        if entered_code == saved_code:
            return redirect('set_new_password')
        else:
            messages.error(request, "Invalid verification code.")

    return render(request, 'groupcore/verify_code.html')


def set_new_password(request):
    if request.method == 'POST':
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return redirect('set_new_password')

        email = request.session.get('reset_email')
        try:
            member = MemberProfile.objects.get(email=email)
            member.set_password(password1)  # change linked User's password
            member.save()

            # Clear all reset-related session data
            request.session.pop('reset_email', None)
            request.session.pop('reset_code', None)
            request.session.pop('reset_expiry', None)

            messages.success(request, "Password has been reset successfully. You can now log in.")
            return redirect('login')
        except MemberProfile.DoesNotExist:
            messages.error(request, "Error resetting password. Please try again.")

    return render(request, 'groupcore/set_new_password.html')


def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('login')

def register_member(request):
    if not request.user.is_authenticated or not request.user.is_chairman():
        return redirect('login')

    if request.method == 'POST':
        form = MemberRegistrationForm(request.POST)
        if form.is_valid():
            member = form.save(commit=False)
            member.set_password(form.cleaned_data['password'])
            member.save()
            messages.success(request, "Member registered successfully.")
            return redirect('register')
    else:
        form = MemberRegistrationForm()

    return render(request, 'groupcore/register.html', {'form': form})


@login_required
def group_settings(request):
    if not _can_manage_group_settings(request.user):
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    today = timezone.localdate()
    settings = GroupSettings.get_active()
    suggested_week_one_start = first_friday_of_year(today.year)
    display_settings = settings or GroupSettings(week_one_start=suggested_week_one_start)

    if request.method == 'POST':
        form = GroupSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Group saving-cycle settings have been saved.")
            return redirect('group_settings')
    else:
        form = GroupSettingsForm(instance=display_settings)

    saving_week = current_saving_week(display_settings.week_one_start, today)
    if request.user.is_treasurer():
        back_url_name = 'treasurer_dashboard'
    elif request.user.is_chairman():
        back_url_name = 'chairman_dashboard'
    else:
        back_url_name = 'home'

    return render(request, 'groupcore/group_settings.html', {
        'form': form,
        'settings_exists': settings is not None,
        'suggested_week_one_start': suggested_week_one_start,
        'saving_week': saving_week,
        'back_url_name': back_url_name,
    })


@login_required
def treasurer_dashboard(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    approved_deposits_qs = DepositSubmission.objects.filter(status='APPROVED')
    purpose_totals = _deposit_purpose_totals(approved_deposits_qs)
    source_balances = _fund_source_balances(approved_deposits_qs)

    total_savings = source_balances['collected']['SAVINGS']

    # Count of all pending deposits
    pending_deposits_count = DepositSubmission.objects.filter(status='PENDING').count()
    pending_deposits_amount = DepositSubmission.objects.filter(status='PENDING').aggregate(total=Sum('amount'))['total'] or 0

    # Sum of unpaid fines
    total_unpaid_fines = Fine.objects.filter(is_paid=False).aggregate(total=Sum('amount'))['total'] or 0

    # Recent deposit submissions
    recent_deposits = DepositSubmission.objects.select_related('member').order_by('-date_submitted')[:10]

    month = timezone.now().month
    year = timezone.now().year
    monthly_purpose_totals = _deposit_purpose_totals(
        approved_deposits_qs.filter(payment_date__year=year, payment_date__month=month)
    )
    approved_loans_qs = LoanRequest.objects.filter(status='APPROVED')
    total_loan_interest = _loan_interest_total(approved_loans_qs)

    # Per-member shares breakdown
    per_member_shares = (
        MemberProfile.objects
        .exclude(is_superuser=True)
        .annotate(shares_total=Sum('deposits__shares_amount', filter=Q(deposits__status='APPROVED')))
        .order_by('username')
    )

    context = {
        'group_total_savings': total_savings,
        'pending_deposits_count': pending_deposits_count,
        'pending_deposits_amount': pending_deposits_amount,
        'total_unpaid_fines': total_unpaid_fines,
        'recent_deposits': recent_deposits,
        'available_funds': source_balances['available'],
        'fund_totals': source_balances['collected'],
        'fund_expenditures': source_balances['expenditures'],
        'fund_assets': source_balances['assets'],
        'purpose_totals': purpose_totals,
        'monthly_purpose_totals': monthly_purpose_totals,
        'per_member_shares': per_member_shares,
        'total_loan_interest': total_loan_interest,
    }

    return render(request, 'groupcore/treasurer_dashboard.html', context)


@login_required
def member_dashboard(request):
    member = request.user
    active_account = get_active_account(request, member)

    if member.is_member() and get_user_active_accounts(member).count() > 1 and not active_account:
        messages.info(request, "Please select a savings account first.")
        return redirect('select_savings_account')

    approved_group_qs = DepositSubmission.objects.filter(status='APPROVED')
    approved_member_qs = DepositSubmission.objects.filter(member=member, status='APPROVED')

    if active_account:
        approved_member_qs = approved_member_qs.filter(account=active_account)

    group_total_savings = approved_group_qs.aggregate(total=Sum('saving_amount'))['total'] or 0

    user_savings_total = approved_member_qs.aggregate(total=Sum('saving_amount'))['total'] or 0
    weeks_paid = approved_member_qs.count()

    
    outstanding_fines_qs = Fine.objects.filter(member=member, is_paid=False)
    if active_account:
        outstanding_fines_qs = outstanding_fines_qs.filter(account=active_account)
    outstanding_fines = outstanding_fines_qs.aggregate(Sum('amount'))['amount__sum'] or 0
    unpaid_fines = outstanding_fines_qs

    
    recent_deposits = DepositSubmission.objects.filter(member=member)
    if active_account:
        recent_deposits = recent_deposits.filter(account=active_account)
    recent_deposits = recent_deposits.order_by('-date_submitted')[:5]
    member_purpose_totals = _deposit_purpose_totals(approved_member_qs)
    group_purpose_totals = _deposit_purpose_totals(approved_group_qs)

    current_year = timezone.now().year
    welfare_due_qs = DepositSubmission.objects.filter(
        member=member,
        status='APPROVED',
        payment_week__year=current_year,
        saving_amount__gt=0,
    )
    if active_account:
        welfare_due_qs = welfare_due_qs.filter(account=active_account)
    welfare_due = welfare_due_qs.count() * 1000
    annual_subscription_due = 10000
    annual_subscription_paid = AnnualSubscription.objects.filter(member=member, year=current_year, is_paid=True).exists()
    share_total = approved_member_qs.aggregate(total=Sum('shares_amount'))['total'] or 0
    subscription_total = approved_member_qs.aggregate(total=Sum('annual_subscription_amount'))['total'] or 0
    approved_loans_qs = LoanRequest.objects.filter(member=member, status='APPROVED')
    if active_account:
        approved_loans_qs = approved_loans_qs.filter(account=active_account)
    outstanding_loans = approved_loans_qs.aggregate(total=Sum('principal'))['total'] or 0
    my_total_loan_interest = _loan_interest_total(approved_loans_qs)

    context = {
        'group_total_savings': group_total_savings,
        'user_savings_total': user_savings_total,
        'weeks_paid': weeks_paid,
        'outstanding_fines': outstanding_fines,
        'recent_deposits': recent_deposits,
        'unpaid_fines': unpaid_fines,
        'welfare_due': welfare_due,
        'annual_subscription_due': 0 if annual_subscription_paid else annual_subscription_due,
        'share_total': share_total,
        'subscription_total': subscription_total,
        'outstanding_loans': outstanding_loans,
        'member_purpose_totals': member_purpose_totals,
        'group_purpose_totals': group_purpose_totals,
        'active_account': active_account,
        'my_total_loan_interest': my_total_loan_interest,
    }
    return render(request, 'groupcore/member_dashboard.html', context)

@login_required
def secretary_dashboard(request):
    total_documents = Document.objects.count()
    personal_documents = Document.objects.filter(user=request.user).count()
    total_members = MemberProfile.objects.exclude(is_superuser=True).count()
    pending_deposits_count = DepositSubmission.objects.filter(status='PENDING').count()
    approved_deposits_count = DepositSubmission.objects.filter(status='APPROVED').count()
    purpose_totals = _deposit_purpose_totals(DepositSubmission.objects.filter(status='APPROVED'))

    approved_loans_qs = LoanRequest.objects.filter(status='APPROVED')
    approved_loans_count = approved_loans_qs.count()
    approved_loans_amount = approved_loans_qs.aggregate(total=Sum('principal'))['total'] or 0
    total_loan_interest = _loan_interest_total(approved_loans_qs)
    recent_approved_loans = approved_loans_qs.select_related('member').order_by('-approved_on', '-requested_on')[:5]
    loan_pending_count = LoanRequest.objects.filter(status__in=[
        LoanRequest.STATUS_PENDING_GUARANTOR,
        LoanRequest.STATUS_PENDING,
    ]).count()
    loan_rejected_count = LoanRequest.objects.filter(status__in=[
        LoanRequest.STATUS_REJECTED,
        LoanRequest.STATUS_REJECTED_GUARANTOR,
    ]).count()

    # Per-member shares breakdown
    per_member_shares = (
        MemberProfile.objects
        .exclude(is_superuser=True)
        .annotate(shares_total=Sum('deposits__shares_amount', filter=Q(deposits__status='APPROVED')))
        .order_by('username')
    )

    return render(request, 'groupcore/secretary_dashboard.html', {
        'total_documents': total_documents,
        'personal_documents': personal_documents,
        'total_members': total_members,
        'pending_deposits_count': pending_deposits_count,
        'approved_deposits_count': approved_deposits_count,
        'purpose_totals': purpose_totals,
        'approved_loans_count': approved_loans_count,
        'approved_loans_amount': approved_loans_amount,
        'recent_approved_loans': recent_approved_loans,
        'loan_pending_count': loan_pending_count,
        'loan_rejected_count': loan_rejected_count,
        'per_member_shares': per_member_shares,
        'total_loan_interest': total_loan_interest,
    })


@login_required
def my_profile(request):
    user = request.user
    editing = request.GET.get('edit') == 'true'

    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            return redirect('my_profile')
    else:
        form = ProfileForm(instance=user)

    # Get the user's national ID document (if uploaded)
    nid_document = Document.objects.filter(user=user, document_type='NID').first()

    return render(request, 'groupcore/my_profile.html', {
        'form': form,
        'nid_document': nid_document,
        'editing': editing,
    })


@login_required
def mobilizer_dashboard(request):
    if not request.user.is_mobilizer:
        messages.error(request, "Access denied.")
        return redirect('login')

    settings = GroupSettings.get_active()
    if not settings:
        messages.error(request, "The saving cycle has not been opened yet. Please contact the Treasurer.")
        return redirect('home')

    saving_week = current_saving_week(settings.week_one_start, timezone.localdate())
    current_week_start = saving_week.week_start

    members = MemberProfile.objects.filter(is_superuser=False)
    paid_count = 0
    unpaid_count = 0

    for member in members:
        deposits = member.deposits.filter(status='APPROVED')
        covered_weeks = []

        for deposit in deposits:
            covered_weeks += deposit.get_covered_weeks()

        if current_week_start in covered_weeks:
            paid_count += 1
        else:
            unpaid_count += 1

    personal_deposits = request.user.deposits.filter(status='APPROVED').count()
    current_week_purpose_totals = _deposit_purpose_totals(
        DepositSubmission.objects.filter(status='APPROVED', payment_week=current_week_start)
    )

    context = {
        'total_members': members.count(),
        'paid_this_week': paid_count,
        'unpaid_this_week': unpaid_count,
        'personal_deposits': personal_deposits,
        'current_week': current_week_start,
        'current_week_number': saving_week.week_number,
        'current_saving_year': saving_week.saving_year,
        'current_week_purpose_totals': current_week_purpose_totals,
    }
    return render(request, 'groupcore/mobilizer_dashboard.html', context)




@login_required
def chairman_dashboard(request):
    if not _is_leadership(request.user):
        return redirect('home')  # Access control

    if request.user.is_chairman():
        dashboard_title = 'Chairman Dashboard'
    elif request.user.is_vice_chairman():
        dashboard_title = 'Vice Chairman Dashboard'
    else:
        dashboard_title = 'Overseer Dashboard'

    total_members = MemberProfile.objects.exclude(is_superuser=True).count()

    # Sum of approved deposits amounts
    approved_deposits_qs = DepositSubmission.objects.filter(status='APPROVED')
    purpose_totals = _deposit_purpose_totals(approved_deposits_qs)
    source_balances = _fund_source_balances(approved_deposits_qs)
    total_deposits = purpose_totals['total']
    total_savings = source_balances['collected']['SAVINGS']
    total_welfare = source_balances['collected']['WELFARE']
    total_fine_deposits = source_balances['collected']['FINES']
    total_annual_subscriptions = source_balances['collected']['ANNUAL_SUBSCRIPTIONS']
    total_shares = source_balances['collected']['SHARES']

    total_documents = Document.objects.count()

    # Sum of expenditures
    total_expenditures = Expenditure.objects.aggregate(total=Sum('amount'))['total'] or 0
    approved_loans_qs = LoanRequest.objects.filter(status='APPROVED')
    total_loan_interest = _loan_interest_total(approved_loans_qs)

    total_assets = Asset.objects.count()

    summary_cards = [
        {'title': 'Total Members', 'count': total_members, 'color': 'success'},
        {'title': 'Savings (UGX)', 'count': f"{total_savings:,}", 'color': 'info'},
        {'title': 'Welfare (UGX)', 'count': f"{total_welfare:,}", 'color': 'warning'},
        {'title': 'Fines (UGX)', 'count': f"{total_fine_deposits:,}", 'color': 'danger'},
        {'title': 'Annual Subs (UGX)', 'count': f"{total_annual_subscriptions:,}", 'color': 'primary'},
        {'title': 'Shares (UGX)', 'count': f"{total_shares:,}", 'color': 'secondary'},
        {'title': 'Documents', 'count': total_documents, 'color': 'secondary'},
        {'title': 'Assets', 'count': total_assets, 'color': 'dark'},
        {'title': 'Expenditures (UGX)', 'count': f"{total_expenditures:,}", 'color': 'primary'}
    ]

    # Weekly payment data for chart
    settings = GroupSettings.get_active()
    weekly_status = {"paid": 0, "unpaid": 0}
    if settings:
        saving_week = current_saving_week(settings.week_one_start, timezone.localdate())
        current_week_start = saving_week.week_start

        for member in MemberProfile.objects.filter(is_superuser=False):
            deposits = member.deposits.filter(status='APPROVED')
            covered_weeks = []
            for deposit in deposits:
                covered_weeks += deposit.get_covered_weeks()
            if current_week_start in covered_weeks:
                weekly_status["paid"] += 1
            else:
                weekly_status["unpaid"] += 1

    # Recent deposits - latest 5 deposits (all statuses)
    recent_deposits = DepositSubmission.objects.select_related('member').order_by('-date_submitted')[:5]

    # Recent fines - latest 5 fines
    recent_fines = Fine.objects.select_related('member').order_by('-date_issued')[:5]

    # Per-member shares breakdown
    per_member_shares = (
        MemberProfile.objects
        .exclude(is_superuser=True)
        .annotate(shares_total=Sum('deposits__shares_amount', filter=Q(deposits__status='APPROVED')))
        .order_by('username')
    )

    context = {
        "summary_cards": summary_cards,
        "total_members": total_members,
        "total_deposits": total_deposits,
        "total_savings": total_savings,
        "total_welfare": total_welfare,
        "total_fines": total_fine_deposits,
        "total_annual_subscriptions": total_annual_subscriptions,
        "total_shares": total_shares,
        "total_documents": total_documents,
        "total_expenditures": total_expenditures,
        "total_assets": total_assets,
        "weekly_status": weekly_status,
        "recent_deposits": recent_deposits,
        "recent_fines": recent_fines,
        "purpose_totals": purpose_totals,
        "per_member_shares": per_member_shares,
        "total_loan_interest": total_loan_interest,
        "dashboard_title": dashboard_title,
        "can_manage_users": request.user.is_chairman(),
        "can_approve_loans": request.user.is_chairman() or request.user.is_vice_chairman(),
    }

    return render(request, 'groupcore/chairman_dashboard.html', context)


@login_required
def vice_chairman_dashboard(request):
    if not request.user.is_vice_chairman():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')
    return chairman_dashboard(request)


@login_required
def overseer_dashboard(request):
    if not request.user.is_overseer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')
    return chairman_dashboard(request)


@login_required
def year_end_settlement(request):
    if not (request.user.is_treasurer() or _is_leadership(request.user)):
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    current_year = timezone.now().year
    target_year = parse_report_year(request.GET.get('year'), default_year=current_year)
    members = MemberProfile.objects.exclude(is_superuser=True)
    rows = []

    approved_deposits_base = DepositSubmission.objects.filter(status='APPROVED')
    approved_loans_base = LoanRequest.objects.filter(status='APPROVED')
    years = merge_year_options(
        years_from_dates(approved_deposits_base, 'payment_week'),
        years_from_dates(approved_loans_base, 'approved_on'),
        selected_year=target_year,
        default_year=current_year,
    )

    approved_deposits_year = approved_deposits_base.filter(payment_week__year=target_year)
    group_savings_total = Decimal(
        approved_deposits_year.aggregate(total=Sum('saving_amount'))['total'] or 0
    )
    approved_loans_year = approved_loans_base.filter(approved_on__year=target_year)
    loan_interest_pool = _loan_interest_total(approved_loans_year)

    for member in members:
        approved_deposits = member.deposits.filter(status='APPROVED', payment_week__year=target_year)
        agg = approved_deposits.aggregate(
            save=Sum('saving_amount'),
            welfare=Sum('welfare_amount'),
            annual=Sum('annual_subscription_amount'),
            fine=Sum('fine_amount'),
            shares=Sum('shares_amount'),
        )
        saving_total = Decimal(agg['save'] or 0)
        welfare_total = Decimal(agg['welfare'] or 0)
        annual_total = Decimal(agg['annual'] or 0)
        fine_total = Decimal(agg['fine'] or 0)
        shares_total = Decimal(agg['shares'] or 0)
        if group_savings_total > 0:
            interest_share = (loan_interest_pool * saving_total) / group_savings_total
        else:
            interest_share = Decimal('0')

        total_deductions = welfare_total + fine_total + annual_total
        gross_distribution = saving_total + interest_share
        net_share = gross_distribution - total_deductions

        rows.append({
            'member': member,
            'saving_total': saving_total,
            'interest_share': interest_share,
            'gross_distribution': gross_distribution,
            'shares_total': shares_total,
            'welfare_total': welfare_total,
            'fine_total': fine_total,
            'annual_total': annual_total,
            'net_share': net_share,
        })

    today = timezone.localdate()
    is_current_year = target_year == current_year
    is_settlement_day = today == date(target_year, 12, 11)

    return render(request, 'groupcore/year_end_settlement.html', {
        'rows': rows,
        'target_year': target_year,
        'years': years,
        'is_current_year': is_current_year,
        'is_settlement_day': is_settlement_day,
        'loan_interest_pool': loan_interest_pool,
        'group_savings_total': group_savings_total,
    })
