from django.test import TestCase
from django.urls import reverse

from groupcore.models import MemberProfile, SavingsAccount
from loans.models import LoanGuarantorApproval, LoanRequest
from messaging.models import MessageRecipient


class LoanGuarantorWorkflowTests(TestCase):
    def setUp(self):
        self.applicant = MemberProfile.objects.create_user(
            username='applicant',
            password='pass12345',
            role='MEMBER',
        )
        self.account = SavingsAccount.objects.create(owner=self.applicant, label='A')
        self.guarantors = [
            MemberProfile.objects.create_user(
                username=f'guarantor{i}',
                password='pass12345',
                role='MEMBER',
            )
            for i in range(1, 4)
        ]
        self.treasurer = MemberProfile.objects.create_user(
            username='treasurer',
            password='pass12345',
            role='TREASURER',
        )
        self.secretary = MemberProfile.objects.create_user(
            username='loansecretary',
            password='pass12345',
            role='SECRETARY',
        )
        self.chairman = MemberProfile.objects.create_user(
            username='chairman',
            password='pass12345',
            role='CHAIRMAN',
        )

    def submit_loan(self):
        self.client.login(username='applicant', password='pass12345')
        response = self.client.post(reverse('request_loan'), {
            'account': str(self.account.id),
            'principal': '100000',
            'duration_months': '6',
            'purpose': 'School fees',
            'guarantors': [str(guarantor.id) for guarantor in self.guarantors],
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        return LoanRequest.objects.get(member=self.applicant)

    def test_request_loan_page_has_guarantor_search(self):
        self.client.login(username='applicant', password='pass12345')

        response = self.client.get(reverse('request_loan'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="guarantor-search"')
        self.assertContains(response, 'placeholder="Search members"')
        self.assertContains(response, 'data-guarantor-option')

    def decide_as_guarantor(self, guarantor, loan, decision, comments=''):
        self.client.logout()
        self.client.login(username=guarantor.username, password='pass12345')
        approval = LoanGuarantorApproval.objects.get(loan=loan, guarantor=guarantor)
        return self.client.post(reverse('guarantor_request_detail', args=[approval.id]), {
            'decision': decision,
            'comments': comments,
        }, follow=True)

    def test_new_loan_waits_for_three_guarantors_before_management(self):
        loan = self.submit_loan()

        self.assertEqual(loan.status, LoanRequest.STATUS_PENDING_GUARANTOR)
        self.assertEqual(loan.guarantor_approvals.count(), 3)
        self.assertEqual(
            MessageRecipient.objects.filter(
                recipient__in=self.guarantors,
                message__subject__contains='Guarantor approval needed',
            ).count(),
            3,
        )

        self.client.logout()
        self.client.login(username='treasurer', password='pass12345')
        queue_response = self.client.get(reverse('pending_loans'))
        self.assertContains(queue_response, "Awaiting Guarantors' Approval")
        blocked_response = self.client.post(reverse('approve_loan', args=[loan.id]))
        self.assertEqual(blocked_response.status_code, 404)

        self.decide_as_guarantor(self.guarantors[0], loan, 'approve', 'Looks fine')
        loan.refresh_from_db()
        self.assertEqual(loan.status, LoanRequest.STATUS_PENDING_GUARANTOR)

        self.decide_as_guarantor(self.guarantors[1], loan, 'approve')
        loan.refresh_from_db()
        self.assertEqual(loan.status, LoanRequest.STATUS_PENDING_GUARANTOR)

        self.decide_as_guarantor(self.guarantors[2], loan, 'approve')
        loan.refresh_from_db()
        self.assertEqual(loan.status, LoanRequest.STATUS_PENDING)
        self.assertEqual(loan.guarantor_approval_count, 3)
        self.assertTrue(
            MessageRecipient.objects.filter(
                recipient=self.treasurer,
                message__subject__contains='Loan ready for management review',
            ).exists()
        )
        self.assertTrue(
            MessageRecipient.objects.filter(
                recipient=self.secretary,
                message__subject__contains='Loan ready for management review',
            ).exists()
        )
        self.assertTrue(
            MessageRecipient.objects.filter(
                recipient=self.chairman,
                message__subject__contains='Loan ready for management review',
            ).exists()
        )

    def test_guarantor_rejection_stops_workflow(self):
        loan = self.submit_loan()

        self.decide_as_guarantor(self.guarantors[0], loan, 'reject', 'Savings are too low')
        loan.refresh_from_db()

        self.assertEqual(loan.status, LoanRequest.STATUS_REJECTED_GUARANTOR)
        self.assertIn('Savings are too low', loan.remarks)
        self.assertTrue(
            MessageRecipient.objects.filter(
                recipient=self.applicant,
                message__subject__contains='Loan rejected by guarantor',
            ).exists()
        )

        self.decide_as_guarantor(self.guarantors[1], loan, 'approve')
        loan.refresh_from_db()
        self.assertEqual(loan.status, LoanRequest.STATUS_REJECTED_GUARANTOR)
