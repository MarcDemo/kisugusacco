from django.urls import path
from . import views

urlpatterns = [
    path('my-fines/', views.my_fines, name='my_fines'),
    path('manage/', views.manage_fines, name='manage_fines'),
    path('add/', views.add_fine, name='add_fine'),
    path('mark-paid/<int:fine_id>/', views.mark_fine_paid, name='mark_fine_paid'),
]
