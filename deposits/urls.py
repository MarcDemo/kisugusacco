from django.urls import path
from . import views

urlpatterns = [
    path('submit/', views.submit_deposit, name='submit_deposit'),
    path('approve/<int:deposit_id>/', views.approve_deposit, name='approve_deposit'),
    path('reject/<int:deposit_id>/', views.reject_deposit, name='reject_deposit'),
    path('delete/<int:deposit_id>/', views.delete_deposit, name='delete_deposit'),
    path('submission/<uuid:batch_id>/approve/', views.approve_deposit_batch, name='approve_deposit_batch'),
    path('submission/<uuid:batch_id>/reject/', views.reject_deposit_batch, name='reject_deposit_batch'),
    path('submission/<uuid:batch_id>/delete/', views.delete_deposit_batch, name='delete_deposit_batch'),
    path('submission/<uuid:batch_id>/edit/', views.edit_deposit_batch, name='edit_deposit_batch'),
    path('submission/<uuid:batch_id>/history/', views.deposit_batch_history, name='deposit_batch_history'),
    path('treasurer/deletions/', views.deposit_deletion_audit, name='deposit_deletion_audit'),
    path('my-contributions/', views.my_contributions, name='my_contributions'),
    path('my-contributions/export/<str:format>/', views.export_my_contributions, name='export_my_contributions'),
    path('treasurer/deposits/', views.manage_deposits, name='manage_deposits'),
    path('treasurer/week-options/', views.treasurer_week_options, name='treasurer_week_options'),
    path('treasurer/reports/', views.treasurer_reports, name='treasurer_reports'),
    path('treasurer/reports/<int:member_id>/<str:format>/', views.download_member_report, name='download_member_report'),
    path('deposits/treasurer/reports/all/<str:format>/', views.download_all_reports, name='download_all_reports'),
    path('treasurer/week-status/', views.current_week_payment_status, name='current_week_status'),
    path('treasurer/week-status/export/<str:format>/', views.export_current_week_payment_status, name='export_current_week_status'),

]
