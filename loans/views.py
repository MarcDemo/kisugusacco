from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import GuarantorDecisionForm, LoanRepaymentForm, LoanRequestForm, TreasurerRateForm
from .models import LoanApprovalAudit, LoanGuarantorApproval, LoanRequest
from groupcore.account_context import get_active_account, get_user_active_accounts
from groupcore.models import MemberProfile
from messaging.services import send_notification


MANAGEMENT_NOTIFICATION_ROLES = ['TREASURER', 'CHAIRMAN', 'VICE_CHAIRMAN', 'SECRETARY']


def _management_users():
    return MemberProfile.objects.filter(
        is_active=True,
        is_superuser=False,
        role__in=MANAGEMENT_NOTIFICATION_ROLES,
    )


def _format_member_name(member):
    return member.get_full_name() or member.username


def _loan_label(loan):
    return f"Loan #{loan.id} for {_format_member_name(loan.member)}"


def _notify_loan_submitted(loan, guarantors):
    applicant_name = _format_member_name(loan.member)
    loan_name = _loan_label(loan)

    send_notification(
        subject=f"Guarantor approval needed: {loan_name}",
        body=(
            f"{applicant_name} has requested a loan of UGX {loan.principal:,.0f}. "
            "Please open your guarantor requests to approve or reject this loan."
        ),
        recipients=guarantors,
        sender=loan.member,
    )
    send_notification(
        subject=f"Loan submitted: {loan_name}",
        body=(
            "Your loan request was submitted successfully and sent to your three "
            "selected guarantors for approval."
        ),
        recipients=[loan.member],
    )


def _notify_management_ready(loan):
    send_notification(
        subject=f"Loan ready for management review: {_loan_label(loan)}",
        body=(
            f"All three guarantors have approved {_format_member_name(loan.member)}'s "
            "loan request. It is now ready for the normal management approval workflow."
        ),
        recipients=_management_users(),
    )
    send_notification(
        subject=f"Loan forwarded to management: {_loan_label(loan)}",
        body=(
            "All three guarantors have approved your loan request. It has been "
            "forwarded to management for review."
        ),
        recipients=[loan.member],
    )


@login_required
def my_loans(request):
    active_account = get_active_account(request, request.user)
    loans = LoanRequest.objects.filter(member=request.user)
    if active_account:
        loans = loans.filter(account=active_account)
    loans = loans.order_by('-requested_on')
    return render(request, 'loans/my_loans.html', {'loans': loans, 'active_account': active_account})


@login_required
def request_loan(request):
    active_account = get_active_account(request, request.user)
    if get_user_active_accounts(request.user).count() > 1 and not active_account:
        messages.info(request, 'Please select a savings account first.')
        return redirect('select_savings_account')

    if request.method == 'POST':
        form = LoanRequestForm(request.POST, user=request.user)
        if form.is_valid():
            guarantors = list(form.cleaned_data['guarantors'])
            with transaction.atomic():
                loan = form.save(commit=False)
                loan.member = request.user
                loan.status = LoanRequest.STATUS_PENDING_GUARANTOR
                if active_account:
                    loan.account = active_account
                loan.full_clean()
                loan.save()

                LoanGuarantorApproval.objects.bulk_create([
                    LoanGuarantorApproval(loan=loan, guarantor=guarantor)
                    for guarantor in guarantors
                ])
                _notify_loan_submitted(loan, guarantors)

            messages.success(request, 'Loan request submitted successfully and sent to guarantors.')
            return redirect('my_loans')
    else:
        form = LoanRequestForm(user=request.user)
        if active_account:
            form.fields['account'].queryset = form.fields['account'].queryset.filter(id=active_account.id)
            form.fields['account'].initial = active_account.id

    return render(request, 'loans/request_loan.html', {'form': form, 'active_account': active_account})


@login_required
def approve_loan(request, loan_id):
    loan = get_object_or_404(LoanRequest, id=loan_id, status=LoanRequest.STATUS_PENDING)

    if request.user.is_treasurer() and not loan.treasurer_approved_by:
        rate_form = TreasurerRateForm(request.POST if request.method == 'POST' else None, instance=loan)
        if request.method == 'POST':
            if rate_form.is_valid():
                rate_form.save()
            else:
                messages.error(request, 'Invalid interest rate.')
                return redirect('pending_loans')
        loan.treasurer_approved_by = request.user
    elif request.user.is_chairman() and loan.treasurer_approved_by and not loan.chairman_approved_by and not loan.vice_chairman_approved_by:
        loan.chairman_approved_by = request.user
    elif request.user.is_vice_chairman() and loan.treasurer_approved_by and not loan.vice_chairman_approved_by and not loan.chairman_approved_by:
        loan.vice_chairman_approved_by = request.user
    else:
        messages.error(request, 'You are not allowed to approve this loan at this stage.')
        return redirect('pending_loans')

    loan.save()
    loan.mark_approved_if_complete()
    messages.success(request, 'Loan approval step recorded successfully.')
    return redirect('pending_loans')


@login_required
@require_POST
def override_loan_approval(request, loan_id):
    if not request.user.is_treasurer():
        messages.error(request, 'Only the Treasurer can record an override approval.')
        return redirect('pending_loans')
    loan = get_object_or_404(
        LoanRequest.objects.prefetch_related('guarantor_approvals'),
        id=loan_id,
        status__in=[LoanRequest.STATUS_PENDING_GUARANTOR, LoanRequest.STATUS_PENDING],
    )
    role = request.POST.get('original_approver_role')
    reason = (request.POST.get('override_reason') or '').strip()
    valid_roles = {choice[0] for choice in LoanApprovalAudit.ROLE_CHOICES}
    if role not in valid_roles or not reason:
        messages.error(request, 'Select the original approver role and give an override reason.')
        return redirect('pending_loans')

    with transaction.atomic():
        if role == 'GUARANTOR':
            pending = list(loan.guarantor_approvals.filter(status=LoanGuarantorApproval.STATUS_PENDING))
            if not pending:
                messages.info(request, 'There are no pending guarantor approvals to override.')
                return redirect('pending_loans')
            for approval in pending:
                approval.status = LoanGuarantorApproval.STATUS_APPROVED
                approval.comments = f'Approved by Treasurer on behalf of Guarantor. Reason: {reason}'
                approval.decided_at = timezone.now()
                approval.save(update_fields=['status', 'comments', 'decided_at'])
                LoanApprovalAudit.objects.create(loan=loan, original_approver_role=role, on_behalf_of=approval.guarantor, actual_approver=request.user, reason=reason)
            loan._prefetched_objects_cache.pop('guarantor_approvals', None)
            loan.mark_pending_if_guarantors_complete()
        else:
            if loan.status == LoanRequest.STATUS_PENDING_GUARANTOR:
                messages.error(request, 'Guarantor approvals must be completed or overridden first.')
                return redirect('pending_loans')
            if role == 'CHAIRMAN':
                loan.chairman_approved_by = request.user
                loan.save(update_fields=['chairman_approved_by'])
            elif role == 'VICE_CHAIRMAN':
                loan.vice_chairman_approved_by = request.user
                loan.save(update_fields=['vice_chairman_approved_by'])
            LoanApprovalAudit.objects.create(loan=loan, original_approver_role=role, actual_approver=request.user, reason=reason)
            loan.mark_approved_if_complete()
    messages.success(request, f'Override recorded: approved by Treasurer on behalf of {dict(LoanApprovalAudit.ROLE_CHOICES)[role]}.')
    return redirect('pending_loans')


@login_required
def reject_loan(request, loan_id):
    loan = get_object_or_404(LoanRequest, id=loan_id, status=LoanRequest.STATUS_PENDING)

    if not (
        request.user.is_treasurer()
        or request.user.is_chairman()
        or request.user.is_vice_chairman()
    ):
        messages.error(request, 'Access denied.')
        return redirect('member_dashboard')

    loan.status = LoanRequest.STATUS_REJECTED
    loan.remarks = f"Rejected by {request.user.username}"
    loan.save(update_fields=['status', 'remarks'])
    messages.warning(request, 'Loan request rejected.')
    return redirect('pending_loans')


@login_required
def pending_loans(request):
    if not (
        request.user.is_treasurer()
        or request.user.is_chairman()
        or request.user.is_vice_chairman()
        or request.user.is_overseer()
        or request.user.is_secretary()
    ):
        messages.error(request, 'Access denied.')
        return redirect('member_dashboard')

    # Heal inconsistent records: if all required approvals exist, move out of pending.
    pending_qs = LoanRequest.objects.filter(status=LoanRequest.STATUS_PENDING, member__is_superuser=False).order_by('-requested_on')
    for loan in pending_qs:
        loan.mark_approved_if_complete()

    loans = (
        LoanRequest.objects
        .filter(status__in=[LoanRequest.STATUS_PENDING_GUARANTOR, LoanRequest.STATUS_PENDING], member__is_superuser=False)
        .select_related('member', 'account')
        .prefetch_related('guarantor_approvals__guarantor')
        .prefetch_related('approval_audits__actual_approver', 'approval_audits__on_behalf_of')
        .order_by('-requested_on')
    )
    return render(request, 'loans/pending_loans.html', {
        'loans': loans,
        'is_treasurer': request.user.is_treasurer(),
        'is_chairman': request.user.is_chairman(),
        'is_vice_chairman': request.user.is_vice_chairman(),
        'is_overseer': request.user.is_overseer(),
        'is_secretary': request.user.is_secretary(),
    })


@login_required
def loan_statuses(request):
    if not (
        request.user.is_treasurer()
        or request.user.is_chairman()
        or request.user.is_vice_chairman()
        or request.user.is_overseer()
    ):
        messages.error(request, 'Access denied.')
        return redirect('member_dashboard')

    all_loans = LoanRequest.objects.filter(member__is_superuser=False).select_related('member', 'account').prefetch_related('repayments').order_by('-requested_on')
    approved_loans = all_loans.filter(status=LoanRequest.STATUS_APPROVED)
    pending_loans_qs = all_loans.filter(status__in=[
        LoanRequest.STATUS_PENDING_GUARANTOR,
        LoanRequest.STATUS_PENDING,
    ])
    rejected_loans = all_loans.filter(status__in=[
        LoanRequest.STATUS_REJECTED,
        LoanRequest.STATUS_REJECTED_GUARANTOR,
    ])

    fully_paid_loans = []
    progress_loans = []
    unpaid_loans = []

    for loan in approved_loans:
        status = loan.repayment_status
        if status == 'UNPAID':
            unpaid_loans.append(loan)
        elif status == 'FULLY_PAID':
            fully_paid_loans.append(loan)
        else:
            progress_loans.append(loan)

    context = {
        'approved_loans': approved_loans,
        'pending_loans': pending_loans_qs,
        'rejected_loans': rejected_loans,
        'fully_paid_loans': fully_paid_loans,
        'progress_loans': progress_loans,
        'unpaid_loans': unpaid_loans,
        'is_treasurer': request.user.is_treasurer(),
    }
    return render(request, 'loans/loan_statuses.html', context)


@login_required
def guarantor_requests(request):
    approvals = (
        LoanGuarantorApproval.objects
        .filter(guarantor=request.user)
        .select_related('loan', 'loan__member', 'loan__account')
        .order_by('-created_at')
    )
    return render(request, 'loans/guarantor_requests.html', {'approvals': approvals})


@login_required
def guarantor_request_detail(request, approval_id):
    approval = get_object_or_404(
        LoanGuarantorApproval.objects.select_related('loan', 'loan__member', 'loan__account', 'guarantor'),
        id=approval_id,
        guarantor=request.user,
    )
    loan = approval.loan

    if request.method == 'POST':
        form = GuarantorDecisionForm(request.POST, instance=approval)
        decision = request.POST.get('decision')

        if approval.status != LoanGuarantorApproval.STATUS_PENDING or loan.status != LoanRequest.STATUS_PENDING_GUARANTOR:
            messages.error(request, 'This guarantor request is no longer awaiting your decision.')
            return redirect('guarantor_requests')

        if decision not in ['approve', 'reject']:
            messages.error(request, 'Please choose approve or reject.')
            return redirect('guarantor_request_detail', approval_id=approval.id)

        if form.is_valid():
            comments = form.cleaned_data.get('comments') or ''
            with transaction.atomic():
                approval = LoanGuarantorApproval.objects.select_for_update().select_related('loan', 'loan__member').get(
                    id=approval.id,
                    guarantor=request.user,
                )
                loan = LoanRequest.objects.select_for_update().select_related('member').get(id=approval.loan_id)

                if approval.status != LoanGuarantorApproval.STATUS_PENDING or loan.status != LoanRequest.STATUS_PENDING_GUARANTOR:
                    messages.error(request, 'This guarantor request is no longer awaiting your decision.')
                    return redirect('guarantor_requests')

                if decision == 'approve':
                    approval.approve(comments=comments)
                    approval.save(update_fields=['status', 'comments', 'decided_at'])
                    send_notification(
                        subject=f"Guarantor approved: {_loan_label(loan)}",
                        body=(
                            f"{_format_member_name(request.user)} approved your loan guarantee request. "
                            f"{loan.guarantor_approval_count} of 3 guarantors have approved."
                        ),
                        recipients=[loan.member],
                    )

                    loan.mark_pending_if_guarantors_complete()
                    loan.refresh_from_db()
                    if loan.status == LoanRequest.STATUS_PENDING:
                        _notify_management_ready(loan)
                    messages.success(request, 'Your approval has been recorded.')
                else:
                    approval.reject(comments=comments)
                    approval.save(update_fields=['status', 'comments', 'decided_at'])
                    loan.status = LoanRequest.STATUS_REJECTED_GUARANTOR
                    rejection_note = f"Rejected by guarantor {_format_member_name(request.user)}"
                    if comments:
                        rejection_note = f"{rejection_note}: {comments}"
                    loan.remarks = rejection_note
                    loan.save(update_fields=['status', 'remarks'])
                    send_notification(
                        subject=f"Loan rejected by guarantor: {_loan_label(loan)}",
                        body=rejection_note,
                        recipients=[loan.member],
                    )
                    messages.warning(request, 'The loan request has been rejected and will not move to management.')

            return redirect('guarantor_requests')
    else:
        form = GuarantorDecisionForm(instance=approval)

    return render(request, 'loans/guarantor_request_detail.html', {
        'approval': approval,
        'loan': loan,
        'form': form,
    })


@login_required
def record_loan_repayment(request, loan_id):
    if not request.user.is_treasurer():
        messages.error(request, 'Only the treasurer can record loan repayments.')
        return redirect('loan_statuses')

    loan = get_object_or_404(LoanRequest, id=loan_id, status=LoanRequest.STATUS_APPROVED)

    if request.method != 'POST':
        return redirect('loan_statuses')

    form = LoanRepaymentForm(request.POST)
    if form.is_valid():
        repayment = form.save(commit=False)
        repayment.loan = loan
        repayment.recorded_by = request.user
        repayment.full_clean()
        repayment.save()
        messages.success(request, 'Loan repayment recorded successfully.')
    else:
        error_text = '; '.join(
            [
                f"{field}: {', '.join(errors)}"
                for field, errors in form.errors.items()
            ]
        )
        messages.error(request, f'Repayment not saved. {error_text}')

    return redirect('loan_statuses')
