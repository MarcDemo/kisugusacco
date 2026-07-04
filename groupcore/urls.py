from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='login', permanent=False), name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('select-account/', views.select_savings_account, name='select_savings_account'),
    path('register/', views.register_member, name='register'), 
    path('chairman/dashboard/', views.chairman_dashboard, name='chairman_dashboard'),
    path('vice-chairman/dashboard/', views.vice_chairman_dashboard, name='vice_chairman_dashboard'),
    path('overseer/dashboard/', views.overseer_dashboard, name='overseer_dashboard'),
    path('treasurer/dashboard/', views.treasurer_dashboard, name='treasurer_dashboard'),
    path('member/dashboard/', views.member_dashboard, name='member_dashboard'),
    path('secretary/dashboard/', views.secretary_dashboard, name='secretary_dashboard'),
    path('mobilizer/dashboard/', views.mobilizer_dashboard, name='mobilizer_dashboard'),
    path('my-profile/', views.my_profile, name='my_profile'),
    path('year-end-settlement/', views.year_end_settlement, name='year_end_settlement'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('verify-code/', views.verify_code, name='verify_code'),
    path('set-new-password/', views.set_new_password, name='set_new_password'),
    path('member-accounts/<int:member_id>/', views.member_accounts_api, name='member_accounts_api'),

]
