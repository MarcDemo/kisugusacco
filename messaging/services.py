from .models import Message, MessageRecipient


def send_notification(subject, body, recipients, sender=None):
    recipient_list = []
    seen = set()

    for recipient in recipients:
        if not recipient or recipient.pk in seen:
            continue
        seen.add(recipient.pk)
        recipient_list.append(recipient)

    if not recipient_list:
        return None

    message = Message.objects.create(
        sender=sender,
        subject=subject,
        body=body,
    )

    MessageRecipient.objects.bulk_create([
        MessageRecipient(message=message, recipient=recipient)
        for recipient in recipient_list
    ])
    return message
