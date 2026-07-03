from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.upload_document, name='upload_document'),
    path('list/', views.list_documents, name='list_documents'),
    path('documents/edit/<int:pk>/', views.edit_document, name='edit_document'),
    path('documents/delete/<int:pk>/', views.delete_document, name='delete_document'),
    
]
