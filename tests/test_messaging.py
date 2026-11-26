"""Inquiries, threads, polling, unread counts and throttled email notifications."""

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.listings.models import ListingStatus
from apps.messaging import services
from apps.messaging.models import Inquiry, Message, MessageRead, Thread

pytestmark = pytest.mark.django_db

INQUIRY = {"name": "Ama Owusu", "email": "ama@example.com", "phone": "+233 20 000 0000", "message": "Is it still available?"}


@pytest.fixture
def owner(make_user):
    return make_user(email="owner@example.com", full_name="Olu Owner", is_landlord=True)


@pytest.fixture
def listing(owner, make_listing):
    return make_listing(owner, title="Sunny flat", purpose="rent")


@pytest.fixture
def buyer(make_user):
    return make_user(email="ama@example.com", full_name="Ama Owusu", is_renter=True)


def inquire(client, listing, **extra):
    return client.post(reverse("messaging:inquire", args=[listing.pk]), {**INQUIRY, **extra}, **extra.pop("headers", {}))


# --- inquiry creation ---------------------------------------------------------------
def test_inquiry_creates_thread_message_and_emails_owner(client, buyer, listing, owner, django_capture_on_commit_callbacks):
    client.force_login(buyer)
    with django_capture_on_commit_callbacks(execute=True):
        response = inquire(client, listing)
    inquiry = Inquiry.objects.get()
    thread = inquiry.thread
    assert response.status_code == 302 and response.url == thread.get_absolute_url()
    assert (thread.listing, thread.buyer, thread.owner) == (listing, buyer, owner)
    assert list(thread.messages.values_list("body", flat=True)) == ["Is it still available?"]
    assert (inquiry.name, inquiry.email, inquiry.phone) == ("Ama Owusu", "ama@example.com", "+233 20 000 0000")
    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert email.to == ["owner@example.com"] and "Sunny flat" in email.subject
    for text in ("Ama Owusu", "ama@example.com", "+233 20 000 0000", "Is it still available?", thread.get_absolute_url()):
        assert text in email.body


def test_second_inquiry_reuses_thread(client, buyer, listing):
    client.force_login(buyer)
    inquire(client, listing)
    inquire(client, listing, message="Also, is parking included?")
    assert Thread.objects.count() == 1 and Inquiry.objects.count() == 2
    assert Thread.objects.get().messages.count() == 2


def test_inquiry_via_htmx_returns_confirmation(client, buyer, listing):
    client.force_login(buyer)
    response = client.post(reverse("messaging:inquire", args=[listing.pk]), INQUIRY, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and "Message sent" in response.content.decode()


def test_invalid_inquiry_shows_errors(client, buyer, listing):
    client.force_login(buyer)
    response = client.post(reverse("messaging:inquire", args=[listing.pk]), {**INQUIRY, "email": "bad", "message": ""}, HTTP_HX_REQUEST="true")
    assert {"email", "message"} <= response.context["form"].errors.keys()
    assert not Inquiry.objects.exists()


def test_inquiry_rules(client, buyer, listing, owner, make_listing, make_user):
    url = reverse("messaging:inquire", args=[listing.pk])
    assert reverse("accounts:login") in client.post(url, INQUIRY).url  # anonymous
    client.force_login(make_user(is_buyer=True, verified=False))
    assert client.post(url, INQUIRY).url == reverse("accounts:verify_email_sent")
    client.force_login(owner)
    client.post(url, INQUIRY)  # own listing
    draft = make_listing(owner, status=ListingStatus.DRAFT)
    client.force_login(buyer)
    assert client.post(reverse("messaging:inquire", args=[draft.pk]), INQUIRY).status_code == 404
    assert not Inquiry.objects.exists()


def test_daily_inquiry_limit(buyer, listing, monkeypatch):
    monkeypatch.setattr(services, "MAX_INQUIRIES_PER_DAY", 2)
    for _ in range(2):
        services.start_inquiry(listing, buyer, **INQUIRY)
    with pytest.raises(services.MessagingError, match="a lot of inquiries"):
        services.start_inquiry(listing, buyer, **INQUIRY)


def test_listing_page_contact_card(client, buyer, listing, owner):
    assert "Sign in to contact" in client.get(listing.get_absolute_url()).content.decode()
    client.force_login(buyer)
    html = client.get(listing.get_absolute_url()).content.decode()
    assert 'name="message"' in html and 'value="Ama Owusu"' in html
    client.force_login(owner)
    assert "This is your listing" in client.get(listing.get_absolute_url()).content.decode()


# --- threads, sending, polling ----------------------------------------------------------
@pytest.fixture
def thread(buyer, listing):
    return services.start_inquiry(listing, buyer, **INQUIRY).thread


def test_only_participants_see_a_thread(client, thread, make_user, owner, buyer):
    client.force_login(make_user(is_buyer=True))
    for name in ("messaging:thread", "messaging:poll"):
        assert client.get(reverse(name, args=[thread.pk])).status_code == 404
    assert client.post(reverse("messaging:send", args=[thread.pk]), {"body": "hi"}).status_code == 404
    for person in (owner, buyer):
        client.force_login(person)
        assert client.get(reverse("messaging:thread", args=[thread.pk])).status_code == 200


def test_owner_sees_contact_details(client, thread, owner):
    client.force_login(owner)
    html = client.get(reverse("messaging:thread", args=[thread.pk])).content.decode()
    assert "ama@example.com" in html and "+233 20 000 0000" in html


def test_reply_and_poll(client, thread, owner, buyer):
    first = thread.messages.get()
    client.force_login(owner)
    response = client.post(reverse("messaging:send", args=[thread.pk]), {"body": "Yes, still available."}, HTTP_HX_REQUEST="true")
    reply = thread.messages.last()
    html = response.content.decode()
    assert "Yes, still available." in html and f"after={reply.pk}" in html  # out-of-band poller moves forward

    client.force_login(buyer)
    poll = client.get(reverse("messaging:poll", args=[thread.pk]), {"after": first.pk}, HTTP_HX_REQUEST="true")
    assert "Yes, still available." in poll.content.decode()
    empty = client.get(reverse("messaging:poll", args=[thread.pk]), {"after": reply.pk}, HTTP_HX_REQUEST="true")
    assert "msg-" not in empty.content.decode() and 'id="poller"' in empty.content.decode()


def test_empty_message_rejected(client, thread, owner):
    client.force_login(owner)
    response = client.post(reverse("messaging:send", args=[thread.pk]), {"body": "   "}, HTTP_HX_REQUEST="true")
    assert response.status_code == 422 and thread.messages.count() == 1


def test_thread_pages_poll_every_five_seconds(client, thread, buyer):
    client.force_login(buyer)
    html = client.get(reverse("messaging:thread", args=[thread.pk])).content.decode()
    assert len(re.findall(r'hx-trigger="(?:load, )?every 5s', html)) >= 3  # messages, thread list, header badge


# --- unread counts -----------------------------------------------------------------------
def test_unread_counts(client, thread, owner, buyer):
    assert services.unread_total(owner) == 1 and services.unread_total(buyer) == 0
    services.post_message(thread, owner, "Reply one")
    services.post_message(thread, owner, "Reply two")
    assert services.unread_total(buyer) == 2 and services.unread_total(owner) == 0
    client.force_login(buyer)
    assert ">2<" in client.get(reverse("messaging:unread_badge")).content.decode()
    client.get(reverse("messaging:thread", args=[thread.pk]))  # opening the thread marks it read
    assert services.unread_total(buyer) == 0
    assert client.get(reverse("messaging:unread_badge")).content.decode().strip() == ""


def test_inbox_lists_threads_with_previews(client, thread, owner):
    client.force_login(owner)
    response = client.get(reverse("messaging:thread_list"))
    t = response.context["threads"][0]
    assert t.unread == 1 and t.last_message.body == "Is it still available?" and t.other_person.full_name == "Ama Owusu"


# --- throttled email notifications -----------------------------------------------------
def test_message_emails_are_throttled(thread, owner, buyer, django_capture_on_commit_callbacks):
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.post_message(thread, owner, "First reply")
        services.post_message(thread, owner, "Second reply")  # within 15 minutes, still unread: no email
    assert [m.to for m in mail.outbox] == [["ama@example.com"]]
    assert "First reply" in mail.outbox[0].body

    # Once the buyer reads, the next message notifies again.
    services.mark_read(thread, buyer)
    with django_capture_on_commit_callbacks(execute=True):
        services.post_message(thread, owner, "Third reply")
    assert len(mail.outbox) == 2

    # After the throttle window, unread or not, they are emailed again.
    MessageRead.objects.filter(thread=thread, user=buyer).update(last_notified_at=timezone.now() - timedelta(minutes=16),
                                                                  last_read_at=None)
    with django_capture_on_commit_callbacks(execute=True):
        services.post_message(thread, owner, "Fourth reply")
    assert len(mail.outbox) == 3


def test_seed_creates_conversations():
    from django.core.management import call_command

    call_command("seed_demo")
    assert Thread.objects.count() >= 3 and Inquiry.objects.count() >= 3
    assert Message.objects.count() >= 7
