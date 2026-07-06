from groupcore.models import MemberProfile, GroupSettings, SavingsAccount
from groupcore.reporting import merge_year_options, parse_report_year, years_from_dates
from groupcore.week_cycle import current_saving_week
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required, user_passes_test
from deposits.models import DepositSubmission
from fines.models import Fine
from documents.models import Document
from incomes.models import ShareContribution, AnnualSubscription
from loans.models import LoanRequest
from django.conf import settings
from datetime import date, datetime
from Assets_Expenditures.models import Asset, Expenditure
from .forms import AddUserForm, EditUserForm, MakeAccountIndependentForm
from django.db.models import Q
from django.utils import timezone
from django.utils.timezone import now
from django.db import transaction
import re
import calendar
from calendar import month_name
from django.http import HttpResponse
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# Create your views here.
def is_chairman(user):
    return user.is_authenticated and user.is_chairman()


def can_manage_users(user):
    return user.is_authenticated and (user.is_chairman() or user.is_secretary())


def user_management_redirect(user):
    if user.is_authenticated and user.is_secretary():
        return 'secretary_dashboard'
    if user.is_authenticated and user.is_chairman():
        return 'chairman_dashboard'
    return 'member_dashboard'


def suggested_username_from_account_label(label):
    tokens = re.findall(r'[A-Za-z0-9]+', label or '')
    if not tokens:
        base = 'Member'
    else:
        first = tokens[0][:1].upper() + tokens[0][1:].lower()
        second_initial = tokens[1][:1].upper() if len(tokens) > 1 else ''
        base = f'{first}{second_initial}'

    username = base
    suffix = 2
    while MemberProfile.objects.filter(username__iexact=username).exists():
        username = f'{base}{suffix}'
        suffix += 1
    return username


def is_leadership(user):
    return user.is_authenticated and (user.is_chairman() or user.is_vice_chairman() or user.is_overseer())

@login_required
def manage_users(request):
    if not can_manage_users(request.user):
        messages.error(request, "Access denied. Only the Chairman or Secretary can manage users.")
        return redirect(user_management_redirect(request.user))

    search_query = (request.GET.get('q') or '').strip()
    users = (
        MemberProfile.objects
        .exclude(is_superuser=True)
        .prefetch_related('savings_accounts')
    )
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(role__icontains=search_query)
            | Q(savings_accounts__label__icontains=search_query)
        ).distinct()
    users = users.order_by('username')
    return render(request, 'chairman/manage_users.html', {
        'users': users,
        'search_query': search_query,
    })

@login_required
def toggle_user_status(request, user_id):
    if not can_manage_users(request.user):
        messages.error(request, "Access denied. Only the Chairman or Secretary can toggle user status.")
        return redirect(user_management_redirect(request.user))

    user = get_object_or_404(MemberProfile, pk=user_id, is_superuser=False)
    if user.id == request.user.id:
        messages.error(request, "You cannot change your own active status.")
        return redirect('manage_users')

    user.is_active = not user.is_active
    user.save()
    status = "activated" if user.is_active else "deactivated"
    messages.success(request, f"{user.username} has been {status}.")
    return redirect('manage_users')


@login_required
def add_user(request):
    if not can_manage_users(request.user):
        messages.error(request, "Access denied. Only the Chairman or Secretary can add users.")
        return redirect(user_management_redirect(request.user))

    if request.method == 'POST':
        form = AddUserForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "User added successfully.")
            return redirect('manage_users')
    else:
        form = AddUserForm()

    return render(request, 'chairman/add_user.html', {'form': form})


@login_required
def user_detail(request, user_id):
    if not can_manage_users(request.user):
        messages.error(request, "Access denied. Only the Chairman or Secretary can view users.")
        return redirect(user_management_redirect(request.user))

    user = get_object_or_404(
        MemberProfile.objects.prefetch_related('savings_accounts'),
        pk=user_id,
        is_superuser=False,
    )
    return render(request, 'chairman/user_detail.html', {
        'managed_user': user,
        'linked_account_count': user.savings_accounts.count(),
    })


@login_required
def edit_user(request, user_id):
    if not can_manage_users(request.user):
        messages.error(request, "Access denied. Only the Chairman or Secretary can edit users.")
        return redirect(user_management_redirect(request.user))

    user = get_object_or_404(MemberProfile, pk=user_id, is_superuser=False)
    accounts = list(user.savings_accounts.order_by('label'))

    if request.method == 'POST':
        form = EditUserForm(request.POST, instance=user)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                submitted_active_ids = {
                    int(account_id)
                    for account_id in request.POST.getlist('active_accounts')
                    if account_id.isdigit()
                }
                for account in accounts:
                    should_be_active = account.id in submitted_active_ids
                    if account.is_active != should_be_active:
                        account.is_active = should_be_active
                        account.save(update_fields=['is_active'])
            messages.success(request, "User updated successfully.")
            return redirect('user_detail', user_id=user.id)
    else:
        form = EditUserForm(instance=user)

    return render(request, 'chairman/edit_user.html', {
        'form': form,
        'managed_user': user,
        'accounts': accounts,
        'linked_account_count': len(accounts),
    })


@login_required
def make_account_independent(request, account_id):
    if not can_manage_users(request.user):
        messages.error(request, "Access denied. Only the Chairman or Secretary can make accounts independent.")
        return redirect(user_management_redirect(request.user))

    account = get_object_or_404(
        SavingsAccount.objects.select_related('owner'),
        pk=account_id,
    )
    linked_account_count = account.owner.savings_accounts.count()
    if linked_account_count <= 1:
        messages.error(request, "This savings account is already the only account under its member.")
        return redirect('user_detail', user_id=account.owner_id)

    initial = {
        'username': suggested_username_from_account_label(account.label),
        'full_name': account.label,
        'role': 'MEMBER',
    }
    if request.method == 'POST':
        form = MakeAccountIndependentForm(request.POST, account=account)
        if form.is_valid():
            with transaction.atomic():
                locked_account = SavingsAccount.objects.select_for_update().select_related('owner').get(pk=account.pk)
                old_owner = locked_account.owner
                if old_owner.savings_accounts.count() <= 1:
                    messages.error(request, "This savings account is already independent.")
                    return redirect('user_detail', user_id=old_owner.id)

                new_member = form.save()
                locked_account.owner = new_member
                locked_account.is_active = True
                locked_account.save(update_fields=['owner', 'is_active'])

                DepositSubmission.objects.filter(account=locked_account).update(member=new_member)
                Fine.objects.filter(account=locked_account).update(member=new_member)
                ShareContribution.objects.filter(account=locked_account).update(member=new_member)
                LoanRequest.objects.filter(account=locked_account).update(member=new_member)

            messages.success(
                request,
                f'Savings account "{locked_account.label}" is now independent under {new_member.username}.',
            )
            return redirect('user_detail', user_id=new_member.id)
    else:
        form = MakeAccountIndependentForm(account=account, initial=initial)

    return render(request, 'chairman/make_account_independent.html', {
        'form': form,
        'account': account,
        'linked_owner': account.owner,
        'linked_account_count': linked_account_count,
    })



#Reports Views

@login_required
def chairman_deposit_report(request):
    if not is_leadership(request.user):
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    # Base queryset: all approved deposits, ordered newest first
    base_qs = DepositSubmission.objects.filter(status='APPROVED').order_by('-payment_week', '-payment_date')

    # Dropdown options (always from base dataset)
    selected_year = parse_report_year(request.GET.get('year'))
    years = merge_year_options(
        years_from_dates(base_qs, 'payment_week'),
        selected_year=selected_year,
    )
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]

    # Get filter parameters
    name_query = request.GET.get('name')
    if not name_query or name_query.strip().lower() == 'none':
        name_query = None
    month_query = request.GET.get('month')

    # Start with full dataset for display
    deposits = base_qs.filter(payment_week__year=selected_year)

    # Apply filters
    if name_query:
        deposits = deposits.filter(member__username__icontains=name_query)

    if month_query:
        try:
            deposits = deposits.filter(payment_week__month=int(month_query))
        except (ValueError, TypeError):
            pass

    # Handle PDF export
    if request.GET.get('export') == 'pdf':
        export_qs = deposits  # export what’s currently filtered

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="member_deposits_report_{selected_year}.pdf"'

        doc = SimpleDocTemplate(response, pagesize=A4)
        styles = getSampleStyleSheet()

        elements = [
            Paragraph(f"Member Deposits Report - {selected_year}", styles['Heading1']),
            Spacer(1, 12),
        ]

        # Table header
        data = [['#', 'Member', 'Saving Week', 'Total', 'Saving', 'Welfare', 'Annual', 'Membership', 'Fine', 'Shares', 'Payment Date', 'Status']]

        # Table rows
        for i, dep in enumerate(export_qs, 1):
            data.append([
                i,
                dep.member.username,
                dep.payment_week.strftime('%Y-%m-%d') if dep.payment_week else '-',
                f"{dep.amount:,.0f}",
                f"{dep.saving_amount:,.0f}",
                f"{dep.welfare_amount:,.0f}",
                f"{dep.annual_subscription_amount:,.0f}",
                f"{dep.membership_amount:,.0f}",
                f"{dep.fine_amount:,.0f}",
                f"{dep.shares_amount:,.0f}",
                dep.payment_date.strftime('%Y-%m-%d') if dep.payment_date else '-',
                dep.status
            ])

        # Table styling
        table = Table(data, colWidths=[18, 62, 42, 38, 38, 38, 36, 48, 34, 36, 44, 40])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4CAF50")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ]))

        elements.append(table)
        doc.build(elements)
        return response

    # Render HTML page
    return render(request, 'chairman/deposit_report.html', {
        'deposits': deposits,
        'years': years,
        'months': months,
        'name_query': name_query,
        'selected_year': selected_year,
        'month_query': month_query,
    })

@login_required
def chairman_fine_report(request):
    if not is_leadership(request.user):
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    fines = Fine.objects.all().order_by('-date_issued')
    return render(request, 'chairman/fine_report.html', {'fines': fines})


@login_required
def chairman_document_report(request):
    if not is_leadership(request.user):
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    documents = Document.objects.all().order_by('-uploaded_at')
    return render(request, 'chairman/document_report.html', {'documents': documents})


@login_required
def chairman_income_report(request):
    if not is_leadership(request.user):
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    shares = ShareContribution.objects.all().order_by('-contribution_date')
    subscriptions = AnnualSubscription.objects.all().order_by('-year', 'member__username')
    return render(request, 'chairman/income_report.html', {
        'shares': shares,
        'subscriptions': subscriptions,
    })


@login_required
def chairman_weekly_payment_status(request):
    if not is_leadership(request.user):
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    settings = GroupSettings.get_active()
    if not settings:
        if request.user.is_chairman() or request.user.is_superuser:
            messages.error(request, "Open the saving cycle in Group Settings before checking current payments.")
            return redirect('group_settings')
        messages.error(request, "The saving cycle has not been opened yet. Please contact the Treasurer.")
        return redirect('chairman_dashboard')

    saving_week = current_saving_week(settings.week_one_start, timezone.localdate())
    current_week_start = saving_week.week_start

    members = MemberProfile.objects.all()
    paid_members = []
    unpaid_members = []

    for member in members:
        has_paid = member.deposits.filter(status='APPROVED', payment_week=current_week_start).exists()
        if has_paid:
            paid_members.append(member)
        else:
            unpaid_members.append(member)

    context = {
        'current_week': current_week_start,
        'current_week_number': saving_week.week_number,
        'current_saving_year': saving_week.saving_year,
        'paid_members': paid_members,
        'unpaid_members': unpaid_members,
    }
    return render(request, 'chairman/current_week_status.html', context)


@login_required
def chairman_asset_report(request):
    if not is_leadership(request.user):
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    assets = Asset.objects.all().order_by('-date_acquired')
    return render(request, 'chairman/asset_report.html', {'assets': assets})


@login_required
def chairman_expenditure_report(request):
    if not is_leadership(request.user):
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    expenditures = Expenditure.objects.all().order_by('-date_spent')
    return render(request, 'chairman/expenditure_report.html', {'expenditures': expenditures})


from django.http import JsonResponse
from django.db.models.functions import ExtractYear

@login_required
def debug_deposit_years(request):
    # Only allow chairman to view this debug info
    if not is_leadership(request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Get distinct years from all approved deposits
    years_in_db = (
        DepositSubmission.objects.filter(status='APPROVED')
        .annotate(year=ExtractYear('payment_date'))
        .values_list('year', flat=True)
        .distinct()
        .order_by('-year')
    )

    return JsonResponse({'years': list(years_in_db)})






