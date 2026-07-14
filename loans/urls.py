from django.urls import path
from . import views

urlpatterns = [
    path('my/', views.my_loans, name='my_loans'),
    path('request/', views.request_loan, name='request_loan'),
    path('guarantor-requests/', views.guarantor_requests, name='guarantor_requests'),
    path('guarantor-requests/<int:approval_id>/', views.guarantor_request_detail, name='guarantor_request_detail'),
    path('statuses/', views.loan_statuses, name='loan_statuses'),
    path('repayment/<int:loan_id>/record/', views.record_loan_repayment, name='record_loan_repayment'),
    path('pending/', views.pending_loans, name='pending_loans'),
    path('approve/<int:loan_id>/', views.approve_loan, name='approve_loan'),
    path('override/<int:loan_id>/', views.override_loan_approval, name='override_loan_approval'),
    path('reject/<int:loan_id>/', views.reject_loan, name='reject_loan'),
]
