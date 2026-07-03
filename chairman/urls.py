from django.urls import path
from . import views

urlpatterns = [
    path('chairman/users/', views.manage_users, name='manage_users'),
    path('chairman/users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('chairman/users/<int:user_id>/edit/', views.edit_user, name='edit_user'),
    path('chairman/users/toggle/<int:user_id>/', views.toggle_user_status, name='toggle_user_status'),
    path('chairman/add-user/', views.add_user, name='add_user'),
    path('chairman/reports/deposits/', views.chairman_deposit_report, name='chairman_deposit_report'),
    path('chairman/reports/fines/', views.chairman_fine_report, name='chairman_fine_report'),
    path('chairman/reports/income/', views.chairman_income_report, name='chairman_income_report'),
    path('chairman/reports/documents/', views.chairman_document_report, name='chairman_document_report'),
    path('chairman/reports/payment-status/', views.chairman_weekly_payment_status, name='chairman_payment_status_report'),
    path('chairman/reports/assets/', views.chairman_asset_report, name='chairman_asset_report'),
    path('chairman/reports/expenditures/', views.chairman_expenditure_report, name='chairman_expenditure_report'),
    path('debug/years/', views.debug_deposit_years, name='debug_deposit_years'),

]
