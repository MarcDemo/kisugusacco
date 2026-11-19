from django.urls import path

from . import views


urlpatterns = [
    path('', views.withdrawal_list, name='withdrawal_list'),
    path('new/', views.withdrawal_create, name='withdrawal_create'),
    path('balance/', views.withdrawal_balance, name='withdrawal_balance'),
    path('<int:withdrawal_id>/', views.withdrawal_detail, name='withdrawal_detail'),
    path('<int:withdrawal_id>/edit/', views.withdrawal_edit, name='withdrawal_edit'),
    path('<int:withdrawal_id>/void/', views.withdrawal_void, name='withdrawal_void'),
]

