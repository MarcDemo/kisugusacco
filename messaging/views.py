from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from .models import Message, MessageRecipient
from .forms import MessageForm
from django.http import Http404

# Create your views here.
User = get_user_model()

@login_required
def inbox(request):
    messages = MessageRecipient.objects.filter(recipient=request.user).select_related('message').order_by('-message__sent_at')
    return render(request, 'messaging/inbox.html', {'messages': messages})

@login_required
def sent_messages(request):
    messages = Message.objects.filter(sender=request.user).order_by('-sent_at')
    return render(request, 'messaging/sent.html', {'messages': messages})

@login_required
def send_message(request):
    if request.method == 'POST':
        form = MessageForm(request.POST, user=request.user)
        if form.is_valid():
            form.save(sender=request.user)
            return redirect('inbox')
    else:
        form = MessageForm(user=request.user)
    return render(request, 'messaging/send_message.html', {'form': form})

@login_required
def message_detail(request, pk):
    user = request.user

    try:
        # Check if user is a recipient
        msg_recipient = MessageRecipient.objects.select_related('message').get(
            message_id=pk,
            recipient=user
        )
        msg = msg_recipient.message

        if not msg_recipient.is_read:
            msg_recipient.is_read = True
            msg_recipient.save()
        return render(request, 'messaging/message_detail.html', {'message': msg, 'from_inbox': True})

    except MessageRecipient.DoesNotExist:
        # Check if user is the sender
        try:
            msg = Message.objects.get(pk=pk, sender=user)
            return render(request, 'messaging/message_detail.html', {'message': msg, 'from_inbox': False})
        except Message.DoesNotExist:
            raise Http404("Message not found")
        
@login_required
def reply_message(request, pk):
    original = get_object_or_404(Message, pk=pk)
    if request.method == 'POST':
        form = MessageForm(request.POST, user=request.user)
        if form.is_valid():
            form.save(sender=request.user)
            return redirect('inbox')
    else:
        form = MessageForm(user=request.user, initial={
            'recipients': original.sender,
            'subject': f"RE: {original.subject}"
        })
    return render(request, 'messaging/reply.html', {'form': form, 'original': original})


