from django.urls import path
from . import views

urlpatterns = [
    path('submit/', views.submit_deposit, name='submit_deposit'),
    path('approve/<int:deposit_id>/', views.approve_deposit, name='approve_deposit'),
    path('reject/<int:deposit_id>/', views.reject_deposit, name='reject_deposit'),
    path('my-contributions/', views.my_contributions, name='my_contributions'),
    path('my-contributions/export/<str:format>/', views.export_my_contributions, name='export_my_contributions'),
    path('treasurer/deposits/', views.manage_deposits, name='manage_deposits'),
    path('treasurer/reports/', views.treasurer_reports, name='treasurer_reports'),
    path('treasurer/reports/<int:member_id>/<str:format>/', views.download_member_report, name='download_member_report'),
    path('deposits/treasurer/reports/all/<str:format>/', views.download_all_reports, name='download_all_reports'),
    path('treasurer/week-status/', views.current_week_payment_status, name='current_week_status'),

]
