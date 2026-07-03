from django.urls import path
from . import views

urlpatterns = [
    path('income/', views.income_list, name='other_income_list'),
    path('income/add/', views.add_income, name='add_income'),
]
