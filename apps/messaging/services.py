"""
Messaging rules: inquiries start threads, replies notify the other person by
email at most once per NOTIFY_THROTTLE while they still have unread messages.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.emails import send_templated_email
from apps.listings.models import ListingStatus

from .models import Inquiry, Message, MessageRead, Thread

NOTIFY_THROTTLE = timedelta(minutes=15)
MAX_INQUIRIES_PER_DAY = 20


class MessagingError(Exception):
    pass


def mark_read(thread, user, when=None):
    MessageRead.objects.update_or_create(thread=thread, user=user, defaults={"last_read_at": when or timezone.now()})


def unread_total(user):
    if not user.is_authenticated:
        return 0
    return sum(t.unread for t in Thread.objects.for_user(user).with_unread(user) if t.unread)


def _should_notify(thread, recipient, now):
    marker = MessageRead.objects.filter(thread=thread, user=recipient).first()
    if marker is None or marker.last_notified_at is None:
        return True
    read_since = marker.last_read_at and marker.last_read_at >= marker.last_notified_at
    return read_since or now - marker.last_notified_at >= NOTIFY_THROTTLE


def _record_notified(thread, recipient, now):
    MessageRead.objects.update_or_create(thread=thread, user=recipient, defaults={"last_notified_at": now})


@transaction.atomic
def start_inquiry(listing, user, name, email, phone, message):
    """Create the inquiry, its thread (or reuse it) and the first message; email the owner."""
    if listing.status != ListingStatus.PUBLISHED:
        raise MessagingError(_("This listing is no longer available."))
    if listing.owner_id == user.pk:
        raise MessagingError(_("You can't send an inquiry about your own listing."))
    since = timezone.now() - timedelta(days=1)
    if Inquiry.objects.filter(sender=user, created_at__gte=since).count() >= MAX_INQUIRIES_PER_DAY:
        raise MessagingError(_("You've sent a lot of inquiries today. Please try again tomorrow."))

    now = timezone.now()
    thread, _created = Thread.objects.get_or_create(
        listing=listing, buyer=user, defaults={"owner": listing.owner, "last_message_at": now}
    )
    Message.objects.create(thread=thread, sender=user, body=message)
    thread.last_message_at = now
    thread.save(update_fields=["last_message_at"])
    inquiry = Inquiry.objects.create(
        listing=listing, sender=user, thread=thread, name=name, email=email, phone=phone, message=message
    )
    mark_read(thread, user, now)
    owner = thread.owner
    transaction.on_commit(lambda: send_templated_email("new_inquiry", owner.email, {
        "owner_name": owner.get_short_name(),
        "listing_title": listing.title,
        "listing_path": listing.get_absolute_url(),
        "thread_path": thread.get_absolute_url(),
        "name": name, "email": email, "phone": phone, "message": message,
    }))
    _record_notified(thread, owner, now)
    return inquiry


@transaction.atomic
def post_message(thread, user, body):
    if not thread.is_participant(user):
        raise MessagingError(_("You're not part of this conversation."))
    body = (body or "").strip()
    if not body:
        raise MessagingError(_("Write a message first."))
    now = timezone.now()
    msg = Message.objects.create(thread=thread, sender=user, body=body[:3000])
    thread.last_message_at = now
    thread.save(update_fields=["last_message_at"])
    mark_read(thread, user, now)
    recipient = thread.other(user)
    if recipient.is_active and not recipient.is_suspended and _should_notify(thread, recipient, now):
        _record_notified(thread, recipient, now)
        transaction.on_commit(lambda: send_templated_email("new_message", recipient.email, {
            "recipient_name": recipient.get_short_name(),
            "sender_name": user.full_name,
            "listing_title": thread.listing.title,
            "thread_path": thread.get_absolute_url(),
            "preview": body[:300],
        }))
    return msg
