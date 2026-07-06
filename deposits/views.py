from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from .forms import DepositSubmissionForm, DirectDepositForm
from .models import DepositSubmission
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from groupcore.models import GroupSettings, MemberProfile
from groupcore.models import SavingsAccount
from groupcore.reporting import merge_year_options, parse_report_year, years_from_dates
from groupcore.week_cycle import current_saving_week
from django.utils import timezone
from django.db.models import Sum
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as ExcelImage
from datetime import datetime, date, timedelta
import os
from django.utils.timezone import now
from openpyxl.utils import get_column_letter
from django.core.mail import send_mail
from fines.models import Fine
from fines.services import delete_deposit_week_missed_saving_fines, missed_saving_fines_can_be_created
from groupcore.account_context import get_active_account, get_user_active_accounts
from loans.models import LoanRepayment, LoanRequest
from decimal import Decimal

# Create your views here.


def _loan_interest_total(queryset):
    total = 0
    for loan in queryset:
        total += loan.total_interest
    return total


def _apply_loan_repayment(member, account, repayment_amount, paid_on, recorded_by, notes=''):
    amount_left = repayment_amount
    if amount_left <= 0:
        return repayment_amount, amount_left

    base_qs = LoanRequest.objects.filter(member=member, status='APPROVED').prefetch_related('repayments').order_by('approved_on', 'requested_on', 'id')
    loans_qs = base_qs
    if account:
        account_loans = loans_qs.filter(account=account)
        loans_qs = account_loans if account_loans.exists() else base_qs

    for loan in loans_qs:
        if amount_left <= 0:
            break
        outstanding = loan.outstanding_balance_as_of(paid_on)
        if outstanding <= 0:
            continue

        allocation = min(amount_left, outstanding)
        repayment = LoanRepayment(
            loan=loan,
            amount=allocation,
            paid_on=paid_on,
            recorded_by=recorded_by,
            notes=notes or 'Recorded from deposit submission.',
        )
        repayment.full_clean()
        repayment.save()
        amount_left -= allocation

    allocated = repayment_amount - amount_left
    return allocated, amount_left

@login_required
def submit_deposit(request):
    if not (request.user.is_member() or request.user.is_secretary() or request.user.is_mobilizer() or request.user.is_chairman()):
        return redirect('login')

    group_settings = GroupSettings.get_active()
    if not group_settings:
        if request.user.is_superuser or request.user.is_treasurer() or request.user.is_chairman():
            messages.error(request, "Open the saving cycle in Group Settings before deposits can be submitted.")
            return redirect('group_settings')
        messages.error(request, "The saving cycle has not been opened yet. Please contact the Treasurer.")
        return redirect('member_dashboard')

    active_account = get_active_account(request, request.user)
    if get_user_active_accounts(request.user).count() > 1 and not active_account:
        messages.info(request, "Please select a savings account first.")
        return redirect('select_savings_account')

    saving_week = current_saving_week(group_settings.week_one_start, timezone.localdate())
    current_week_start = saving_week.week_start

    if request.method == 'POST':
        form = DepositSubmissionForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            account = active_account or form.cleaned_data.get('account')
            payment_week = current_week_start
            proof = form.cleaned_data['proof']
            remarks = form.cleaned_data.get('remarks', '')
            payment_date = form.cleaned_data['payment_date']
            payment_time = form.cleaned_data['payment_time']
            saving_amount = form.cleaned_data.get('saving_amount') or 0
            welfare_amount = form.cleaned_data.get('welfare_amount') or 0
            annual_subscription_amount = form.cleaned_data.get('annual_subscription_amount') or 0
            membership_amount = form.cleaned_data.get('membership_amount') or 0
            fine_amount = form.cleaned_data.get('fine_amount') or 0
            shares_amount = form.cleaned_data.get('shares_amount') or 0
            loan_repayment_amount = form.cleaned_data.get('loan_repayment_amount') or 0
            total_amount = form.cleaned_data['amount']  # computed in form.clean()

            # Create deposit record (amount auto-computed in model.save())
            deposit = DepositSubmission(
                member=request.user,
                account=account,
                submitted_by=request.user,
                payment_week=payment_week,
                starting_week=payment_week,
                weeks_covered=1,
                saving_amount=saving_amount,
                welfare_amount=welfare_amount,
                annual_subscription_amount=annual_subscription_amount,
                membership_amount=membership_amount,
                fine_amount=fine_amount,
                shares_amount=shares_amount,
                loan_repayment_amount=loan_repayment_amount,
                proof=proof,
                remarks=remarks,
                payment_date=payment_date,
                payment_time=payment_time,
                status='PENDING'
            )
            deposit.full_clean()
            deposit.save()
            amount = deposit.amount  # use the auto-computed total for emails

            # Send acknowledgment email
            subject = "Deposit Submission Acknowledgment"
            message = (
                f"Dear {request.user.first_name or request.user.username},\n\n"
                f"Thank you for your deposit submission of UGX {amount:,} "
                f"made on {payment_date.strftime('%d %B %Y')}.\n\n"
                "The Treasury Department will review and approve it soon. "
                "You will receive a confirmation email after it has been approved.\n\n"
                "Regards,\n"
                "Land Investment Group"
            )
            from_email = "info.landinvestmentgroup@gmail.com"
            recipient_list = [request.user.email]

            send_mail(subject, message, from_email, recipient_list, fail_silently=False)

            # --- Send notification email to treasurer(s) ---
            treasurer_emails = list(
                MemberProfile.objects.filter(role='TREASURER').values_list('email', flat=True)
            )
            if treasurer_emails:
                subject_treasurer = "New Deposit Submission - Action Required"
                message_treasurer = (
                    f"Dear Treasurer,\n\n"
                    f"Member {request.user.get_full_name() or request.user.username} "
                    f"has submitted a deposit of UGX {amount:,} "
                    f"for week of {payment_week.strftime('%d %B %Y')}.\n\n"
                    "Please log in to the system to review and process this deposit.\n\n"
                    "Regards,\n"
                    "Land Investment Group"
                )
                send_mail(
                    subject_treasurer,
                    message_treasurer,
                    "info.landinvestmentgroup@gmail.com",
                    treasurer_emails,
                    fail_silently=False
                )

            messages.success(request, f"Weekly saving submitted for week of {payment_week}.")
            return redirect('member_dashboard')
    else:
        form = DepositSubmissionForm(user=request.user)
        if active_account:
            form.fields['account'].queryset = SavingsAccount.objects.filter(id=active_account.id)
            form.fields['account'].initial = active_account.id

    # Build the set of account IDs that have an active (approved) loan for this user
    # so the template can show the Loan Repayment checkbox only for those accounts.
    import json as _json
    loan_account_ids = list(
        LoanRequest.objects.filter(member=request.user, status='APPROVED')
        .exclude(account__isnull=True)
        .values_list('account_id', flat=True)
        .distinct()
    )
    return render(request, 'deposits/submit_deposit.html', {
        'form': form,
        'loan_account_ids_json': _json.dumps(loan_account_ids),
    })


@login_required
def approve_deposit(request, deposit_id):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    deposit = get_object_or_404(DepositSubmission, id=deposit_id, status='PENDING')
    deposit.status = 'APPROVED'
    deposit.reviewed_by = request.user
    deposit.date_reviewed = timezone.now()
    deposit.save()
    cleared_fines = delete_deposit_week_missed_saving_fines(deposit)

    if deposit.loan_repayment_amount and deposit.loan_repayment_amount > 0:
        allocated, unallocated = _apply_loan_repayment(
            member=deposit.member,
            account=deposit.account,
            repayment_amount=deposit.loan_repayment_amount,
            paid_on=deposit.payment_date,
            recorded_by=request.user,
            notes=f'Deposit approval repayment (Deposit #{deposit.id}).',
        )
        if allocated > 0:
            messages.success(request, f"UGX {allocated:,.0f} was posted to loan repayment.")
        if unallocated > 0:
            messages.warning(request, f"UGX {unallocated:,.0f} could not be posted because no outstanding approved loan balance was found.")

    # Send approval email
    send_mail(
        subject="Deposit Approved",
        message=(
            f"Dear {deposit.member.get_full_name()},\n\n"
            f"Your deposit of {deposit.amount} made on {deposit.payment_date.strftime('%d %B %Y')} "
            f"has been approved by the Treasury Department.\n\n"
            "Thank you for your continued commitment.\n\n"
            "Regards,\nTreasury Department"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[deposit.member.email],
        fail_silently=True,
    )

    if cleared_fines:
        messages.success(request, f"{cleared_fines} missed-week fine(s) were cleared for this account/week.")
    messages.success(request, "Deposit approved and member notified by email.")
    return redirect('treasurer_dashboard')



@login_required
def reject_deposit(request, deposit_id):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    deposit = get_object_or_404(DepositSubmission, id=deposit_id, status='PENDING')
    deposit.status = 'REJECTED'
    deposit.reviewed_by = request.user
    deposit.date_reviewed = timezone.now()
    deposit.save()

    # Send rejection email
    send_mail(
        subject="Deposit Rejected",
        message=(
            f"Dear {deposit.member.get_full_name()},\n\n"
            f"Your deposit of {deposit.amount} made on {deposit.payment_date.strftime('%d %B %Y')} "
            "has been rejected. Please contact the Treasury Department for more information.\n\n"
            "Regards,\nTreasury Department"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[deposit.member.email],
        fail_silently=True,
    )

    messages.warning(request, "Deposit rejected and member notified by email.")
    return redirect('treasurer_dashboard')





MONTHS = [
    ("01", "January"), ("02", "February"), ("03", "March"), ("04", "April"),
    ("05", "May"), ("06", "June"), ("07", "July"), ("08", "August"),
    ("09", "September"), ("10", "October"), ("11", "November"), ("12", "December")
]


def _optional_int(value, min_value=None, max_value=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if min_value is not None and parsed < min_value:
        return None
    if max_value is not None and parsed > max_value:
        return None
    return parsed


def _approved_deposit_totals(queryset):
    totals = queryset.filter(status='APPROVED').aggregate(
        total=Sum('amount'),
        saving=Sum('saving_amount'),
        welfare=Sum('welfare_amount'),
        annual_subscription=Sum('annual_subscription_amount'),
        membership=Sum('membership_amount'),
        fine=Sum('fine_amount'),
        shares=Sum('shares_amount'),
        loan_repayment=Sum('loan_repayment_amount'),
    )
    return {
        key: totals.get(key) or Decimal('0')
        for key in [
            'total',
            'saving',
            'welfare',
            'annual_subscription',
            'membership',
            'fine',
            'shares',
            'loan_repayment',
        ]
    }


def _my_contributions_data(request):
    user = request.user
    active_account = get_active_account(request, user)
    base_deposits = DepositSubmission.objects.filter(member=user)
    if active_account:
        base_deposits = base_deposits.filter(account=active_account)

    current_year = timezone.localdate().year
    selected_year = _optional_int(request.GET.get('year'), min_value=1, max_value=9999) or current_year
    selected_month = _optional_int(request.GET.get('month'), min_value=1, max_value=12)

    deposits = base_deposits.order_by('-payment_week', '-date_submitted')
    deposits = deposits.filter(payment_week__year=selected_year)
    if selected_month:
        deposits = deposits.filter(payment_week__month=selected_month)
    years = merge_year_options(
        years_from_dates(base_deposits, 'payment_week'),
        selected_year=selected_year,
        default_year=current_year,
    )

    return {
        'active_account': active_account,
        'deposits': deposits,
        'years': years,
        'selected_year': selected_year,
        'selected_month': f'{selected_month:02d}' if selected_month else '',
        'selected_month_number': selected_month,
        'approved_totals': _approved_deposit_totals(deposits),
    }


def _month_label(month_number):
    if not month_number:
        return 'All Months'
    return dict(MONTHS).get(f'{month_number:02d}', 'All Months')


def _safe_filename_part(value):
    value = str(value or 'none')
    return ''.join(char if char.isalnum() or char in ('-', '_') else '_' for char in value)


def _my_contributions_filename(account, selected_year, selected_month, extension):
    account_label = _safe_filename_part(account.label if account else 'no_account')
    if selected_year and selected_month:
        period = f'{selected_year}_{selected_month:02d}'
    elif selected_year:
        period = str(selected_year)
    elif selected_month:
        period = f'month_{selected_month:02d}'
    else:
        period = 'all'
    return f'my_contributions_{account_label}_{period}.{extension}'


def _proof_reference(deposit):
    return deposit.proof.name if deposit.proof else '-'


def _my_contributions_report_meta(user, active_account, contribution_data):
    return {
        'member_name': user.get_full_name() or user.username,
        'username': user.username,
        'account_label': active_account.label if active_account else '-',
        'year_label': contribution_data['selected_year'] or 'All Years',
        'month_label': _month_label(contribution_data['selected_month_number']),
        'generated_at': now().strftime('%Y-%m-%d %H:%M'),
    }


def _my_contributions_detail_rows(deposits):
    rows = []
    for deposit in deposits:
        rows.append([
            deposit.payment_week.strftime('%Y-%m-%d') if deposit.payment_week else '-',
            deposit.account.label if deposit.account else '-',
            deposit.amount,
            deposit.saving_amount,
            deposit.welfare_amount,
            deposit.annual_subscription_amount,
            deposit.membership_amount,
            deposit.fine_amount,
            deposit.shares_amount,
            deposit.loan_repayment_amount,
            deposit.status.title(),
            deposit.payment_date.strftime('%Y-%m-%d') if deposit.payment_date else '-',
            deposit.payment_time.strftime('%H:%M') if deposit.payment_time else '-',
            deposit.submitted_by.username if deposit.submitted_by else '-',
            deposit.remarks or '-',
            _proof_reference(deposit),
        ])
    return rows


def _money(value):
    return f"UGX {Decimal(value or 0):,.0f}"


def _export_my_contributions_pdf(user, active_account, contribution_data, deposits):
    response = HttpResponse(content_type='application/pdf')
    filename = _my_contributions_filename(
        active_account,
        contribution_data['selected_year'],
        contribution_data['selected_month_number'],
        'pdf',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    doc = SimpleDocTemplate(response, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    meta = _my_contributions_report_meta(user, active_account, contribution_data)
    totals = contribution_data['approved_totals']

    elements = [
        Paragraph(f"Financial Report for {meta['member_name']}", styles['Title']),
        Paragraph(
            f"Username: {meta['username']} | Savings Account: {meta['account_label']} | "
            f"Period: {meta['year_label']} / {meta['month_label']} | Generated: {meta['generated_at']}",
            styles['Normal'],
        ),
        Spacer(1, 10),
    ]

    summary_data = [
        ['Approved Total', 'Saving', 'Welfare', 'Annual', 'Membership', 'Fine', 'Shares', 'Loan Repayment'],
        [
            _money(totals['total']),
            _money(totals['saving']),
            _money(totals['welfare']),
            _money(totals['annual_subscription']),
            _money(totals['membership']),
            _money(totals['fine']),
            _money(totals['shares']),
            _money(totals['loan_repayment']),
        ],
    ]
    summary_table = Table(summary_data)
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 12))

    detail_headers = [
        'Saving Week', 'Account', 'Total', 'Saving', 'Welfare', 'Annual', 'Membership', 'Fine',
        'Shares', 'Loan Repay', 'Status', 'Payment Date', 'Payment Time',
        'Submitted By', 'Remarks', 'Proof Ref',
    ]
    detail_rows = []
    for row in _my_contributions_detail_rows(deposits):
        detail_rows.append([
            row[0], row[1], _money(row[2]), _money(row[3]), _money(row[4]),
            _money(row[5]), _money(row[6]), _money(row[7]), _money(row[8]),
            _money(row[9]), row[10], row[11], row[12], row[13], row[14], row[15],
        ])
    if not detail_rows:
        detail_rows = [['No matching deposits'] + [''] * (len(detail_headers) - 1)]

    detail_table = Table(
        [detail_headers] + detail_rows,
        repeatRows=1,
        colWidths=[54, 40, 46, 42, 42, 42, 48, 38, 40, 50, 44, 54, 46, 54, 66, 82],
    )
    detail_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8f5ee')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 6.5),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(detail_table)
    doc.build(elements)
    return response


def _export_my_contributions_excel(user, active_account, contribution_data, deposits):
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = _my_contributions_filename(
        active_account,
        contribution_data['selected_year'],
        contribution_data['selected_month_number'],
        'xlsx',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    wb = Workbook()
    ws = wb.active
    ws.title = 'Financial Report'
    meta = _my_contributions_report_meta(user, active_account, contribution_data)
    totals = contribution_data['approved_totals']

    ws.merge_cells('A1:P1')
    ws['A1'] = f"Financial Report for {meta['member_name']}"
    ws['A1'].font = Font(size=14, bold=True)
    ws['A1'].alignment = Alignment(horizontal='center')

    meta_rows = [
        ('Username', meta['username']),
        ('Savings Account', meta['account_label']),
        ('Year', meta['year_label']),
        ('Month', meta['month_label']),
        ('Generated', meta['generated_at']),
    ]
    for row_number, (label, value) in enumerate(meta_rows, start=3):
        ws.cell(row=row_number, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row_number, column=2, value=value)

    summary_start = 10
    ws.cell(row=summary_start, column=1, value='Approved Totals').font = Font(bold=True)
    summary_headers = ['Total', 'Saving', 'Welfare', 'Annual', 'Membership', 'Fine', 'Shares', 'Loan Repayment']
    for column, header in enumerate(summary_headers, start=1):
        cell = ws.cell(row=summary_start + 1, column=column, value=header)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(start_color='198754', end_color='198754', fill_type='solid')
    summary_values = [
        totals['total'],
        totals['saving'],
        totals['welfare'],
        totals['annual_subscription'],
        totals['membership'],
        totals['fine'],
        totals['shares'],
        totals['loan_repayment'],
    ]
    for column, value in enumerate(summary_values, start=1):
        ws.cell(row=summary_start + 2, column=column, value=float(value))

    detail_start = summary_start + 5
    ws.cell(row=detail_start, column=1, value='Deposit Details').font = Font(bold=True)
    headers = [
        'Saving Week', 'Account', 'Total', 'Saving', 'Welfare', 'Annual', 'Membership', 'Fine',
        'Shares', 'Loan Repayment', 'Status', 'Payment Date', 'Payment Time',
        'Submitted By', 'Remarks', 'Proof Reference',
    ]
    for column, header in enumerate(headers, start=1):
        cell = ws.cell(row=detail_start + 1, column=column, value=header)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(start_color='198754', end_color='198754', fill_type='solid')
        cell.alignment = Alignment(horizontal='center')

    for row_number, row in enumerate(_my_contributions_detail_rows(deposits), start=detail_start + 2):
        for column, value in enumerate(row, start=1):
            if isinstance(value, Decimal):
                value = float(value)
            ws.cell(row=row_number, column=column, value=value)

    for column_cells in ws.columns:
        max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
        ws.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max_length + 3, 42)

    wb.save(response)
    return response


@login_required
def export_my_contributions(request, format):
    contribution_data = _my_contributions_data(request)
    active_account = contribution_data['active_account']
    if not active_account:
        if get_user_active_accounts(request.user).exists():
            messages.info(request, "Please select a savings account before downloading your report.")
            return redirect('select_savings_account')
        messages.error(request, "No active savings account was found for your profile.")
        return redirect('my_contributions')

    deposits = list(
        contribution_data['deposits'].select_related('account', 'submitted_by')
    )

    if format == 'pdf':
        return _export_my_contributions_pdf(request.user, active_account, contribution_data, deposits)
    if format == 'excel':
        return _export_my_contributions_excel(request.user, active_account, contribution_data, deposits)
    return HttpResponse("Invalid format", status=400)


@login_required
def my_contributions(request):
    contribution_data = _my_contributions_data(request)
    active_account = contribution_data['active_account']

    context = {
        'deposits': contribution_data['deposits'],
        'total_approved': contribution_data['approved_totals']['total'],
        'approved_totals': contribution_data['approved_totals'],
        'years': contribution_data['years'],
        'selected_year': contribution_data['selected_year'],
        'selected_month': contribution_data['selected_month'],
        'months': MONTHS,  # add this
        'active_account': active_account,
        'export_querystring': request.GET.urlencode(),
    }
    return render(request, 'deposits/my_contributions.html', context)



@login_required
def manage_deposits(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    pending_deposits = DepositSubmission.objects.filter(status='PENDING').order_by('-date_submitted')
    form = DirectDepositForm(request.POST or None, request.FILES or None)

    if request.method == 'POST':
        form = DirectDepositForm(request.POST, request.FILES)
        if form.is_valid():
            member = form.cleaned_data['member']
            account = form.cleaned_data.get('account')
            proof = form.cleaned_data['proof']
            remarks = form.cleaned_data.get('remarks', '')
            payment_date = form.cleaned_data['payment_date']
            payment_time = form.cleaned_data['payment_time']
            payment_week = form.cleaned_data['payment_week']
            saving_amount = form.cleaned_data.get('saving_amount') or 0
            welfare_amount = form.cleaned_data.get('welfare_amount') or 0
            annual_subscription_amount = form.cleaned_data.get('annual_subscription_amount') or 0
            membership_amount = form.cleaned_data.get('membership_amount') or 0
            fine_amount = form.cleaned_data.get('fine_amount') or 0
            shares_amount = form.cleaned_data.get('shares_amount') or 0
            loan_repayment_amount = form.cleaned_data.get('loan_repayment_amount') or 0

            # Save deposit with auto-approval (amount auto-computed in model.save())
            deposit = DepositSubmission(
                member=member,
                account=account,
                submitted_by=request.user,
                reviewed_by=request.user,
                payment_week=payment_week,
                starting_week=payment_week,
                weeks_covered=1,
                saving_amount=saving_amount,
                welfare_amount=welfare_amount,
                annual_subscription_amount=annual_subscription_amount,
                membership_amount=membership_amount,
                fine_amount=fine_amount,
                shares_amount=shares_amount,
                loan_repayment_amount=loan_repayment_amount,
                proof=proof,
                remarks=remarks,
                status='APPROVED',
                payment_date=payment_date,
                payment_time=payment_time,
                date_reviewed=timezone.now(),
                date_submitted=timezone.now(),
            )
            deposit.full_clean()
            deposit.save()
            cleared_fines = delete_deposit_week_missed_saving_fines(deposit)

            if deposit.loan_repayment_amount and deposit.loan_repayment_amount > 0:
                allocated, unallocated = _apply_loan_repayment(
                    member=deposit.member,
                    account=deposit.account,
                    repayment_amount=deposit.loan_repayment_amount,
                    paid_on=deposit.payment_date,
                    recorded_by=request.user,
                    notes=f'Direct deposit repayment (Deposit #{deposit.id}).',
                )
                if unallocated > 0:
                    messages.warning(request, f"UGX {unallocated:,.0f} could not be posted because no outstanding approved loan balance was found.")

            if cleared_fines:
                messages.success(request, f"{cleared_fines} missed-week fine(s) were cleared for this account/week.")
            messages.success(request, f"Deposit for {member.username} added for week of {payment_week}.")
            return redirect('manage_deposits')

    return render(request, 'deposits/manage_deposits.html', {
        'pending_deposits': pending_deposits,
        'form': form,
    })

@login_required
def treasurer_reports(request):
    selected_year = parse_report_year(request.GET.get('year'))
    approved_deposits_base = DepositSubmission.objects.filter(status='APPROVED')
    years = merge_year_options(
        years_from_dates(approved_deposits_base, 'payment_week'),
        years_from_dates(LoanRequest.objects.filter(status='APPROVED'), 'approved_on'),
        selected_year=selected_year,
    )
    members = MemberProfile.objects.exclude(is_superuser=True)

    report_data = []
    for member in members:
        approved_deposits = member.deposits.filter(
            status='APPROVED',
            payment_week__year=selected_year,
        )
        total_amount = approved_deposits.aggregate(Sum('amount'))['amount__sum'] or 0
        total_saving = approved_deposits.aggregate(Sum('saving_amount'))['saving_amount__sum'] or 0
        total_welfare = approved_deposits.aggregate(Sum('welfare_amount'))['welfare_amount__sum'] or 0
        total_annual = approved_deposits.aggregate(Sum('annual_subscription_amount'))['annual_subscription_amount__sum'] or 0
        total_membership = approved_deposits.aggregate(Sum('membership_amount'))['membership_amount__sum'] or 0
        total_fine = approved_deposits.aggregate(Sum('fine_amount'))['fine_amount__sum'] or 0
        total_shares = approved_deposits.aggregate(Sum('shares_amount'))['shares_amount__sum'] or 0
        total_interest = _loan_interest_total(
            member.loan_requests.filter(status='APPROVED', approved_on__year=selected_year)
        )
        total_weeks = approved_deposits.count()

        report_data.append({
            'member': member,
            'total_amount': total_amount,
            'total_weeks': total_weeks,
            'total_saving': total_saving,
            'total_welfare': total_welfare,
            'total_annual': total_annual,
            'total_membership': total_membership,
            'total_fine': total_fine,
            'total_shares': total_shares,
            'total_interest': total_interest,
        })

    return render(request, 'deposits/treasurer_reports.html', {
        'report_data': report_data,
        'selected_year': selected_year,
        'years': years,
    })



def download_member_report(request, member_id, format):
    selected_year = parse_report_year(request.GET.get('year'))
    member = get_object_or_404(MemberProfile, id=member_id)
    deposits = member.deposits.filter(
        status='APPROVED',
        payment_week__year=selected_year,
    ).order_by('payment_week')

    if format == 'pdf':
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{member.username}_report_{selected_year}.pdf"'

        doc = SimpleDocTemplate(response, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        full_name = member.get_full_name() or member.username
        title = Paragraph(f"<b>Contribution Report for {full_name} - {selected_year}</b>", styles['Title'])
        elements.append(title)
        elements.append(Spacer(1, 12))

        # Table header
        data = [
            ['#', 'Week', 'Total', 'Saving', 'Welfare', 'Annual', 'Membership', 'Fine', 'Shares', 'Date Submitted', 'Payment Date', 'Payment Time', 'Remarks']
        ]

        # Table rows
        for i, deposit in enumerate(deposits, start=1):
            data.append([
                i,
                deposit.payment_week.strftime('%Y-%m-%d'),
                f"{deposit.amount:,.0f}",
                f"{deposit.saving_amount:,.0f}",
                f"{deposit.welfare_amount:,.0f}",
                f"{deposit.annual_subscription_amount:,.0f}",
                f"{deposit.membership_amount:,.0f}",
                f"{deposit.fine_amount:,.0f}",
                f"{deposit.shares_amount:,.0f}",
                deposit.date_submitted.strftime('%Y-%m-%d'),
                deposit.payment_date.strftime('%Y-%m-%d'),
                deposit.payment_time.strftime('%H:%M'),
                deposit.remarks or '-'
            ])

        # Table styling
        table = Table(data, colWidths=[18, 50, 48, 42, 42, 42, 52, 38, 38, 56, 50, 44, 62])
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

    elif format == 'excel':
        

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Member Contributions"

        full_name = member.get_full_name() or member.username
        ws.merge_cells('A1:M1')
        ws['A1'] = f"Contribution Report for {full_name} - {selected_year}"
        ws['A1'].font = Font(size=14, bold=True)
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')

        # Optional: Add group logo
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo.png')
        if os.path.exists(logo_path):
            img = ExcelImage(logo_path)
            img.height = 60
            img.width = 60
            ws.add_image(img, 'F1')

        # Define headers
        headers = ['#', 'Week', 'Total (UGX)', 'Saving', 'Welfare', 'Annual', 'Membership', 'Fine', 'Shares', 'Date Submitted', 'Payment Date', 'Payment Time', 'Remarks']
        ws.append(headers)

        # Header styling
        header_fill = PatternFill(start_color='4CAF50', end_color='4CAF50', fill_type='solid')
        header_font = Font(bold=True, color="FFFFFF")
        border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin")
        )

        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=2, column=col_num)
            cell.value = header
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
            cell.border = border

        # Fill data rows
        total_amount = 0
        for i, deposit in enumerate(deposits, start=1):
            row = [
                i,
                deposit.payment_week.strftime('%Y-%m-%d'),
                float(deposit.amount),
                float(deposit.saving_amount),
                float(deposit.welfare_amount),
                float(deposit.annual_subscription_amount),
                float(deposit.membership_amount),
                float(deposit.fine_amount),
                float(deposit.shares_amount),
                deposit.date_submitted.strftime('%Y-%m-%d'),
                deposit.payment_date.strftime('%Y-%m-%d'),
                deposit.payment_time.strftime('%H:%M'),
                deposit.remarks or '-'
            ]
            ws.append(row)
            total_amount += float(deposit.amount)

        last_data_row = 2 + len(deposits)

        # Total row
        total_label_cell = ws.cell(row=last_data_row + 1, column=2, value="TOTAL")
        total_label_cell.font = Font(bold=True)
        total_label_cell.alignment = Alignment(horizontal='right')

        ws.cell(row=last_data_row + 1, column=3, value=total_amount).font = Font(bold=True)

        # Footer with generated timestamp
        ws.merge_cells(start_row=last_data_row + 3, start_column=1, end_row=last_data_row + 3, end_column=13)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        footer_cell = ws.cell(row=last_data_row + 3, column=1)
        footer_cell.value = f"Generated on: {timestamp}"
        footer_cell.font = Font(italic=True, size=10)
        footer_cell.alignment = Alignment(horizontal='right')

        # Auto column width
        for col in ws.columns:
            max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
            ws.column_dimensions[get_column_letter(col[0].column)].width = max_length + 2

        # Download response
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{member.username}_report_{selected_year}.xlsx"'
        wb.save(response)
        return response


def download_all_reports(request, format):
    selected_year = parse_report_year(request.GET.get('year'))
    members = MemberProfile.objects.all()

    if format == 'pdf':
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = [
            Paragraph(f"Group Contribution Report (All Members) - {selected_year}", styles['Heading1']),
            Paragraph(f"Generated on: {now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']),
            Spacer(1, 12),
        ]

        for member in members:
            deposits = member.deposits.filter(
                status='APPROVED',
                payment_week__year=selected_year,
            ).order_by('payment_week')
            if not deposits.exists():
                continue

            elements.append(Paragraph(f"Member: {member.get_full_name() or member.username}", styles['Heading3']))
            data = [['Week', 'Total', 'Saving', 'Welfare', 'Annual', 'Membership', 'Fine', 'Shares', 'Payment Date', 'Payment Time']]
            total_amount = 0

            for dep in deposits:
                data.append([
                    dep.payment_week.strftime('%Y-%m-%d'),
                    f"{dep.amount:,.0f}",
                    f"{dep.saving_amount:,.0f}",
                    f"{dep.welfare_amount:,.0f}",
                    f"{dep.annual_subscription_amount:,.0f}",
                    f"{dep.membership_amount:,.0f}",
                    f"{dep.fine_amount:,.0f}",
                    f"{dep.shares_amount:,.0f}",
                    dep.payment_date.strftime('%Y-%m-%d'),
                    dep.payment_time.strftime('%H:%M'),
                ])
                total_amount += dep.amount

            data.append(['TOTAL', f"{total_amount:,.0f}", '', '', '', '', '', '', '', ''])
            table = Table(data, colWidths=[54, 50, 48, 48, 48, 56, 42, 42, 58, 52])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 24))

        doc.build(elements)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="all_member_reports_{selected_year}.pdf"'
        return response

    if format == 'excel':
        wb = Workbook()
        ws = wb.active
        ws.title = f"Contributions {selected_year}"

        ws.merge_cells('A1:K1')
        ws['A1'] = f"Group Contribution Report (All Members) - {selected_year}"
        ws['A1'].font = Font(size=14, bold=True)
        ws['A1'].alignment = Alignment(horizontal='center')

        ws.append(["Generated on:", now().strftime('%Y-%m-%d %H:%M')])
        ws.append([])
        ws.append(["Member", "Week", "Total (UGX)", "Saving", "Welfare", "Annual", "Membership", "Fine", "Shares", 'Payment Date', 'Payment Time'])

        for member in members:
            deposits = member.deposits.filter(
                status='APPROVED',
                payment_week__year=selected_year,
            ).order_by('payment_week')
            total_amount = 0

            for dep in deposits:
                ws.append([
                    member.get_full_name() or member.username,
                    dep.payment_week.strftime('%Y-%m-%d'),
                    float(dep.amount),
                    float(dep.saving_amount),
                    float(dep.welfare_amount),
                    float(dep.annual_subscription_amount),
                    float(dep.membership_amount),
                    float(dep.fine_amount),
                    float(dep.shares_amount),
                    dep.payment_date.strftime('%Y-%m-%d'),
                    dep.payment_time.strftime('%H:%M'),
                ])
                total_amount += float(dep.amount)

            if deposits.exists():
                ws.append([
                    f"TOTAL for {member.get_full_name() or member.username}",
                    "",
                    total_amount,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ])
                ws.append([])

        for i, column_cells in enumerate(ws.columns, 1):
            max_length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
            col_letter = get_column_letter(i)
            ws.column_dimensions[col_letter].width = max_length + 4

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="all_member_reports_{selected_year}.xlsx"'
        return response

    return HttpResponse("Invalid format", status=400)
    

def _can_view_current_week_status(user):
    return (
        user.is_treasurer()
        or user.is_mobilizer()
        or user.is_chairman()
        or user.is_vice_chairman()
        or user.is_overseer()
    )


def _current_week_settings_redirect(request):
    group_settings = GroupSettings.get_active()
    if group_settings:
        return group_settings, None
    if request.user.is_superuser or request.user.is_treasurer() or request.user.is_chairman():
        messages.error(request, "Open the saving cycle in Group Settings before checking current payments.")
        return None, redirect('group_settings')
    messages.error(request, "The saving cycle has not been opened yet. Please contact the Treasurer.")
    return None, redirect('member_dashboard')


def _status_entry(member, account, has_paid):
    return {
        'member': member,
        'member_name': member.get_full_name() or member.username,
        'account': account,
        'account_label': account.label if account else '-',
        'has_paid': has_paid,
        'status_label': 'Paid' if has_paid else 'Not Paid',
    }


def _current_week_payment_status_data(request, create_fines=False):
    group_settings = GroupSettings.get_active()
    saving_week = current_saving_week(group_settings.week_one_start, timezone.localdate())
    current_week_start = saving_week.week_start
    fines_can_be_created = create_fines and missed_saving_fines_can_be_created(current_week_start)
    grace_ends_on = current_week_start + timedelta(days=2)

    paid_entries = []
    unpaid_entries = []

    members = MemberProfile.objects.filter(is_superuser=False).order_by('username')
    for member in members:
        member_accounts = list(SavingsAccount.objects.filter(owner=member, is_active=True).order_by('label'))
        accounts_to_check = member_accounts or [None]

        for account in accounts_to_check:
            deposit_filter = {
                'status': 'APPROVED',
                'payment_week': current_week_start,
            }
            if account:
                deposit_filter['account'] = account
            else:
                deposit_filter['account__isnull'] = True

            has_paid = member.deposits.filter(**deposit_filter).exists()
            entry = _status_entry(member, account, has_paid)
            if has_paid:
                paid_entries.append(entry)
                continue

            unpaid_entries.append(entry)
            if fines_can_be_created:
                account_note = f" for account {account.label}" if account else ""
                Fine.objects.get_or_create(
                    member=member,
                    account=account,
                    fine_type='MISSED_WEEKLY_SAVING',
                    reference_week=current_week_start,
                    defaults={
                        'reason': f'Failed to save{account_note} for week closing {current_week_start}',
                        'amount': 2000,
                        'issued_by': request.user,
                    }
                )

    return {
        'current_week': current_week_start,
        'current_week_number': saving_week.week_number,
        'current_saving_year': saving_week.saving_year,
        'paid_entries': paid_entries,
        'unpaid_entries': unpaid_entries,
        'all_entries': paid_entries + unpaid_entries,
        'fines_can_be_created': fines_can_be_created,
        'grace_ends_on': grace_ends_on,
    }


def _current_week_status_filename(data, extension):
    return f"current_week_payment_status_week_{data['current_week_number']}_{data['current_week'].strftime('%Y-%m-%d')}.{extension}"


def _export_current_week_status_excel(data):
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{_current_week_status_filename(data, "xlsx")}"'

    wb = Workbook()
    ws = wb.active
    ws.title = 'Current Payments'
    ws['A1'] = f"Payment Status for Week {data['current_week_number']} Closing {data['current_week'].strftime('%Y-%m-%d')}"
    ws['A1'].font = Font(size=14, bold=True)
    ws.merge_cells('A1:E1')

    headers = ['#', 'Member', 'Account', 'Status', 'Week Closing']
    for column, header in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=column, value=header)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(start_color='198754', end_color='198754', fill_type='solid')
        cell.alignment = Alignment(horizontal='center')

    for row_number, entry in enumerate(data['all_entries'], start=4):
        ws.cell(row=row_number, column=1, value=row_number - 3)
        ws.cell(row=row_number, column=2, value=entry['member_name'])
        ws.cell(row=row_number, column=3, value=entry['account_label'])
        ws.cell(row=row_number, column=4, value=entry['status_label'])
        ws.cell(row=row_number, column=5, value=data['current_week'].strftime('%Y-%m-%d'))

    for column_cells in ws.columns:
        max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
        ws.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max_length + 3, 42)

    wb.save(response)
    return response


def _export_current_week_status_pdf(data):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{_current_week_status_filename(data, "pdf")}"'

    doc = SimpleDocTemplate(response, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(f"Payment Status for Week {data['current_week_number']}", styles['Title']),
        Paragraph(f"Week Closing: {data['current_week'].strftime('%A, %d %b %Y')}", styles['Normal']),
        Paragraph(f"Paid: {len(data['paid_entries'])} | Unpaid: {len(data['unpaid_entries'])}", styles['Normal']),
        Spacer(1, 12),
    ]

    table_rows = [['#', 'Member', 'Account', 'Status']]
    for index, entry in enumerate(data['all_entries'], start=1):
        table_rows.append([index, entry['member_name'], entry['account_label'], entry['status_label']])
    if len(table_rows) == 1:
        table_rows.append(['-', 'No members found', '-', '-'])

    table = Table(table_rows, repeatRows=1, colWidths=[35, 210, 120, 90])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(table)
    doc.build(elements)
    return response


@login_required
def export_current_week_payment_status(request, format):
    if not _can_view_current_week_status(request.user):
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    _group_settings, redirect_response = _current_week_settings_redirect(request)
    if redirect_response:
        return redirect_response

    data = _current_week_payment_status_data(request, create_fines=False)
    if format == 'excel':
        return _export_current_week_status_excel(data)
    if format == 'pdf':
        return _export_current_week_status_pdf(data)
    return HttpResponse("Invalid format", status=400)


@login_required
def current_week_payment_status(request):
    if not _can_view_current_week_status(request.user):
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    _group_settings, redirect_response = _current_week_settings_redirect(request)
    if redirect_response:
        return redirect_response

    context = _current_week_payment_status_data(request, create_fines=True)
    return render(request, 'deposits/current_week_status.html', context)
