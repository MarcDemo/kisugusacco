from django.urls import path
from . import views

urlpatterns = [
    path('assets/', views.list_assets, name='list_assets'),
    path('assets/add/', views.add_asset, name='add_asset'),
    path('expenditures/', views.list_expenditures, name='list_expenditures'),
    path('expenditures/add/', views.add_expenditure, name='add_expenditure'),
]
