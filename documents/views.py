from django.shortcuts import render, redirect, get_object_or_404
from .forms import DocumentForm
from .models import Document
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.contrib import messages


# Create your views here.
@login_required
def upload_document(request):
    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('list_documents')
    else:
        form = DocumentForm()
    return render(request, 'documents/upload_document.html', {'form': form})


@login_required
def list_documents(request):
    documents = Document.objects.all().order_by('-uploaded_at')

    # Get filter/search inputs
    doc_type = request.GET.get("type")
    search_query = request.GET.get("search")

    if doc_type:
        documents = documents.filter(document_type=doc_type)

    if search_query:
        documents = documents.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    context = {
        'documents': documents
    }
    return render(request, 'documents/list_documents.html', context)


@login_required
def edit_document(request, pk):
    document = get_object_or_404(Document, pk=pk)
    
    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES, instance=document)
        if form.is_valid():
            form.save()
            return redirect('list_documents')
    else:
        form = DocumentForm(instance=document)

    return render(request, 'documents/edit_document.html', {'form': form, 'document': document})


@login_required
def delete_document(request, pk):
    document = get_object_or_404(Document, pk=pk)

    if request.method == 'POST':
        document.delete()
        messages.success(request, "Document deleted successfully.")
        return redirect('list_documents')

    return render(request, 'documents/delete_document.html', {'document': document})