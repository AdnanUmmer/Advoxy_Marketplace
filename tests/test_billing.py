"""Payments: adapter, Stripe webhook signature verification, fulfilment, subscriptions, capacity, pages."""

import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import stripe
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import AgencyTeam, AgentProfile
from apps.billing import services
from apps.billing.models import FeaturedPlacement, Plan, Purchase, Subscription, WebhookEvent
from apps.listings import rules
from apps.listings.models import Listing, ListingPhoto, ListingStatus

pytestmark = pytest.mark.django_db
SECRET = "whsec_test_secret"
WEBHOOK = "/billing/webhook/stripe/"


@pytest.fixture(autouse=True)
def stripe_settings(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_dummy"
    settings.STRIPE_WEBHOOK_SECRET = SECRET
    settings.SITE_URL = "https://advoxy.test"


def sign(payload: bytes, secret=SECRET, timestamp=None):
    t = timestamp or int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


def event(etype, obj, eid=None):
    return json.dumps({"id": eid or f"evt_{etype}_{time.time_ns()}", "object": "event", "type": etype,
                       "data": {"object": obj}}).encode()


def post_event(client, payload, signature=None, on_commit=None):
    return client.post(WEBHOOK, data=payload, content_type="application/json",
                       HTTP_STRIPE_SIGNATURE=signature if signature is not None else sign(payload))


@pytest.fixture
def landlord(make_user):
    return make_user(email="landlord@example.com", is_landlord=True)


@pytest.fixture
def agent(make_user):
    user = make_user(email="agent@example.com", is_agent=True)
    AgentProfile.objects.create(user=user)
    return user


def ready(listing):
    ListingPhoto.objects.create(listing=listing, image="seed/x.jpg")
    return listing


# --- webhook signature verification (SPEC: verify signatures) -------------------------------
def test_valid_signature_is_accepted(client):
    payload = event("customer.created", {"id": "cus_1", "object": "customer"})
    assert post_event(client, payload).status_code == 200


@pytest.mark.parametrize("bad", [
    "t=1,v1=deadbeef",                                    # wrong signature
    "",                                                   # missing header
    None,                                                 # computed below with the wrong secret
])
def test_bad_signatures_are_rejected(client, bad):
    payload = event("checkout.session.completed", {"id": "cs_1", "object": "checkout.session", "mode": "payment",
                                                   "payment_status": "paid", "metadata": {"purchase_id": "1"}})
    signature = sign(payload, secret="whsec_attacker") if bad is None else bad
    response = post_event(client, payload, signature)
    assert response.status_code == 400
    assert not WebhookEvent.objects.exists()


def test_tampered_body_is_rejected(client):
    payload = event("charge.refunded", {"id": "ch_1", "object": "charge", "payment_intent": "pi_1"})
    signature = sign(payload)
    response = post_event(client, payload.replace(b"pi_1", b"pi_2"), signature)
    assert response.status_code == 400


def test_old_timestamp_is_rejected(client):
    payload = event("customer.created", {"id": "cus_1", "object": "customer"})
    assert post_event(client, payload, sign(payload, timestamp=int(time.time()) - 3600)).status_code == 400


def test_missing_webhook_secret_rejects_everything(client, settings):
    settings.STRIPE_WEBHOOK_SECRET = ""
    payload = event("customer.created", {"id": "cus_1", "object": "customer"})
    assert post_event(client, payload).status_code == 400


def test_webhook_only_accepts_post(client):
    assert client.get(WEBHOOK).status_code == 405


# --- one-time purchases --------------------------------------------------------------------
def completed_checkout(purchase, pi="pi_123", paid=True):
    return {"id": purchase.checkout_session_id or "cs_x", "object": "checkout.session", "mode": "payment",
            "payment_status": "paid" if paid else "unpaid", "status": "complete", "client_reference_id": str(purchase.user_id),
            "payment_intent": pi, "metadata": {"purchase_id": str(purchase.pk), "kind": purchase.kind}}


def test_extra_slot_purchase_adds_capacity_once(client, landlord, make_listing, django_capture_on_commit_callbacks):
    for _ in range(2):
        make_listing(landlord, purpose="rent", status=ListingStatus.PUBLISHED)
    assert not rules.capacity_for(landlord).can_activate
    purchase = Purchase.objects.create(user=landlord, kind=Purchase.Kind.EXTRA_LISTING, description="slot",
                                       amount=Decimal("10"), currency="USD", checkout_session_id="cs_slot")
    payload = event("checkout.session.completed", completed_checkout(purchase), eid="evt_same")
    with django_capture_on_commit_callbacks(execute=True):
        assert post_event(client, payload).status_code == 200
        assert post_event(client, payload).status_code == 200  # Stripe retry: processed once
    purchase.refresh_from_db()
    assert purchase.status == Purchase.Status.PAID and purchase.payment_intent_id == "pi_123"
    assert purchase.expires_at.date() == (timezone.now() + timedelta(days=30)).date()
    cap = rules.capacity_for(landlord)
    assert cap.total == 3 and cap.can_activate
    assert WebhookEvent.objects.count() == 1
    assert len([m for m in mail.outbox if "receipt" in m.subject.lower()]) == 1


def test_expired_slot_no_longer_counts(landlord):
    Purchase.objects.create(user=landlord, kind=Purchase.Kind.EXTRA_LISTING, description="slot", amount=10, currency="USD",
                            status=Purchase.Status.PAID, expires_at=timezone.now() - timedelta(minutes=1))
    assert rules.capacity_for(landlord).total == 2


def test_unpaid_checkout_does_not_fulfil(client, landlord):
    purchase = Purchase.objects.create(user=landlord, kind=Purchase.Kind.EXTRA_LISTING, description="slot", amount=10, currency="USD")
    post_event(client, event("checkout.session.completed", completed_checkout(purchase, paid=False)))
    purchase.refresh_from_db()
    assert purchase.status == Purchase.Status.PENDING


def test_featured_placement_stacks_and_ends(landlord, make_listing):
    listing = make_listing(landlord, purpose="rent")
    p1 = Purchase.objects.create(user=landlord, kind=Purchase.Kind.FEATURED, listing=listing, description="f", amount=25, currency="USD")
    p2 = Purchase.objects.create(user=landlord, kind=Purchase.Kind.FEATURED, listing=listing, description="f", amount=25, currency="USD")
    services.fulfil_purchase(p1, "pi_1")
    services.fulfil_purchase(p2, "pi_2")
    services.fulfil_purchase(p2, "pi_2")  # idempotent
    placements = list(FeaturedPlacement.objects.order_by("starts_at"))
    assert len(placements) == 2 and placements[1].starts_at == placements[0].ends_at  # second extends the first
    listing.refresh_from_db()
    assert listing.is_featured
    # After the first placement ends the listing stays featured; after both end it is unfeatured.
    assert services.end_featured_placements(now=placements[0].ends_at + timedelta(minutes=1)) == 0
    assert services.end_featured_placements(now=placements[1].ends_at + timedelta(minutes=1)) == 1
    listing.refresh_from_db()
    assert not listing.is_featured


def test_staff_featured_listing_without_placement_is_untouched(landlord, make_listing):
    listing = make_listing(landlord, is_featured=True)
    services.end_featured_placements()
    listing.refresh_from_db()
    assert listing.is_featured


def test_refund_marks_purchase(client, landlord):
    purchase = Purchase.objects.create(user=landlord, kind=Purchase.Kind.EXTRA_LISTING, description="slot", amount=10,
                                       currency="USD", status=Purchase.Status.PAID, payment_intent_id="pi_9")
    post_event(client, event("charge.refunded", {"id": "ch_9", "object": "charge", "payment_intent": "pi_9"}))
    purchase.refresh_from_db()
    assert purchase.status == Purchase.Status.REFUNDED


# --- subscriptions --------------------------------------------------------------------------
def sub_object(sub_id, status="active", ref=None, period_end=None, cancel=False):
    return {"id": sub_id, "object": "subscription", "status": status, "customer": "cus_1", "cancel_at_period_end": cancel,
            "metadata": {"subscription_ref": str(ref)} if ref else {},
            "items": {"object": "list", "data": [{"id": "si_1", "current_period_end": period_end or int(time.time()) + 30 * 86400}]}}


def test_subscription_lifecycle_controls_agent_capacity(client, agent, make_listing, django_capture_on_commit_callbacks):
    plan = Plan.objects.get(code="agent")
    draft = ready(make_listing(agent, status=ListingStatus.DRAFT))
    with pytest.raises(rules.TransitionError, match="plan|subscription"):
        rules.owner_transition(draft, agent, "submit")
    local = Subscription.objects.create(user=agent, plan=plan)
    # The subscription event can arrive before checkout.session.completed: matched by metadata.
    post_event(client, event("customer.subscription.created", sub_object("sub_1", "active", ref=local.pk)))
    local.refresh_from_db()
    assert local.status == "active" and local.provider_subscription_id == "sub_1" and local.current_period_end
    assert rules.capacity_for(agent).total == 15
    rules.owner_transition(draft, agent, "submit")
    # Invoice paid (current API shape) records revenue once and emails a receipt.
    invoice = {"id": "in_1", "object": "invoice", "amount_paid": 2900, "currency": "usd",
               "parent": {"subscription_details": {"subscription": "sub_1", "metadata": {}}},
               "lines": {"object": "list", "data": [{"period": {"end": int(time.time()) + 30 * 86400}}]}}
    with django_capture_on_commit_callbacks(execute=True):
        post_event(client, event("invoice.paid", invoice))
        post_event(client, event("invoice.paid", invoice))  # a different event id, same invoice
    payments = Purchase.objects.filter(kind=Purchase.Kind.SUBSCRIPTION)
    assert payments.count() == 1 and payments.get().amount == Decimal("29.00")
    assert any("receipt" in m.subject.lower() for m in mail.outbox)
    # Cancellation at period end keeps access; deletion removes it.
    post_event(client, event("customer.subscription.updated", sub_object("sub_1", "active", cancel=True)))
    local.refresh_from_db()
    assert local.cancel_at_period_end and local.grants_access
    post_event(client, event("customer.subscription.deleted", sub_object("sub_1", "canceled")))
    local.refresh_from_db()
    assert local.status == "canceled"
    assert rules.capacity_for(agent).needs_subscription


def test_agency_plan_is_shared_by_its_agents(make_user, make_listing):
    owner = make_user(is_agency=True)
    agency = AgencyTeam.objects.create(owner=owner, name="Team")
    member = make_user(is_agent=True)
    AgentProfile.objects.create(user=member, agency=agency)
    Subscription.objects.create(user=owner, plan=Plan.objects.get(code="agency-starter"), status="active")
    make_listing(member, agency=agency, status=ListingStatus.PUBLISHED)
    make_listing(owner, agency=agency, status=ListingStatus.PUBLISHED)
    cap = rules.capacity_for(member)
    assert cap.total == 50 and cap.used == 2  # whole team counts against the agency limit


def test_extra_slot_needs_plan_for_agents(agent):
    with pytest.raises(services.BillingError, match="plan"):
        services.start_extra_listing_checkout(agent)


# --- checkout creation through the adapter (Stripe API stubbed) --------------------------------
@pytest.fixture
def fake_stripe(monkeypatch):
    calls = []

    def create(**params):
        calls.append(params)
        return SimpleNamespace(id=f"cs_test_{len(calls)}", url=f"https://checkout.stripe.com/c/pay/cs_test_{len(calls)}")

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(create))
    return calls


def test_buy_slot_starts_checkout(client, landlord, fake_stripe):
    client.force_login(landlord)
    response = client.post(reverse("billing:buy_slot"))
    assert response.status_code == 302 and response.url.startswith("https://checkout.stripe.com/")
    params = fake_stripe[0]
    assert params["mode"] == "payment" and params["customer_email"] == "landlord@example.com"
    item = params["line_items"][0]["price_data"]
    assert item["unit_amount"] == 1000 and item["currency"] == "usd"
    assert params["success_url"] == "http://testserver/billing/success/?session_id={CHECKOUT_SESSION_ID}"
    purchase = Purchase.objects.get()
    assert purchase.status == "pending" and purchase.checkout_session_id == "cs_test_1"
    assert params["metadata"]["purchase_id"] == str(purchase.pk)


def test_subscribe_starts_recurring_checkout(client, agent, fake_stripe):
    client.force_login(agent)
    client.post(reverse("billing:subscribe", args=["agent"]))
    params = fake_stripe[0]
    assert params["mode"] == "subscription"
    assert params["line_items"][0]["price_data"]["recurring"] == {"interval": "month"}
    assert params["line_items"][0]["price_data"]["unit_amount"] == 2900
    assert params["subscription_data"]["metadata"]["plan"] == "agent"


@pytest.mark.parametrize("code", ["agency-starter"])
def test_wrong_audience_cannot_subscribe(client, agent, fake_stripe, code):
    client.force_login(agent)
    client.post(reverse("billing:subscribe", args=[code]))
    assert not fake_stripe and not Subscription.objects.exists()


def test_feature_requires_own_published_listing(client, landlord, make_user, make_listing, fake_stripe):
    other = make_listing(make_user(is_seller=True))
    draft = make_listing(landlord, status=ListingStatus.DRAFT)
    client.force_login(landlord)
    assert client.post(reverse("billing:feature", args=[other.pk])).status_code == 404
    client.post(reverse("billing:feature", args=[draft.pk]))
    assert not fake_stripe
    live = make_listing(landlord, purpose="rent")
    response = client.post(reverse("billing:feature", args=[live.pk]))
    assert response.url.startswith("https://checkout.stripe.com/")
    assert fake_stripe[0]["line_items"][0]["price_data"]["unit_amount"] == 2500


def test_provider_error_is_shown_not_crashed(client, landlord, monkeypatch):
    def boom(**params):
        raise stripe.AuthenticationError("Invalid API Key provided")

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(boom))
    client.force_login(landlord)
    response = client.post(reverse("billing:buy_slot"), follow=True)
    assert "couldn" in response.content.decode() and Purchase.objects.get().status == "failed"


def test_success_page_fulfils_without_webhook(client, landlord, monkeypatch, django_capture_on_commit_callbacks):
    purchase = Purchase.objects.create(user=landlord, kind=Purchase.Kind.EXTRA_LISTING, description="slot",
                                       amount=10, currency="USD", checkout_session_id="cs_back")
    session = stripe.checkout.Session.construct_from(completed_checkout(purchase, pi="pi_back"), "sk_test_dummy")
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", staticmethod(lambda *a, **k: session))
    client.force_login(landlord)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.get(reverse("billing:success"), {"session_id": "cs_back"})
    purchase.refresh_from_db()
    assert purchase.status == "paid" and "Payment received" in response.content.decode()


def test_success_page_ignores_other_peoples_sessions(client, landlord, make_user, monkeypatch):
    purchase = Purchase.objects.create(user=landlord, kind=Purchase.Kind.EXTRA_LISTING, description="slot",
                                       amount=10, currency="USD", checkout_session_id="cs_back")
    session = stripe.checkout.Session.construct_from(completed_checkout(purchase), "sk_test_dummy")
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", staticmethod(lambda *a, **k: session))
    client.force_login(make_user(is_buyer=True))
    client.get(reverse("billing:success"), {"session_id": "cs_back"})
    purchase.refresh_from_db()
    assert purchase.status == "pending"


def test_cancel_at_period_end(client, agent, monkeypatch):
    sub = Subscription.objects.create(user=agent, plan=Plan.objects.get(code="agent"), status="active",
                                      provider_subscription_id="sub_c", current_period_end=timezone.now() + timedelta(days=10))
    snapshot = stripe.Subscription.construct_from(sub_object("sub_c", "active", cancel=True), "sk_test_dummy")
    monkeypatch.setattr(stripe.Subscription, "modify", staticmethod(lambda *a, **k: snapshot))
    client.force_login(agent)
    client.post(reverse("billing:cancel"))
    sub.refresh_from_db()
    assert sub.cancel_at_period_end and sub.grants_access


# --- pages ---------------------------------------------------------------------------------------
def test_pricing_and_billing_pages(client, agent):
    html = client.get(reverse("billing:pricing")).content.decode()
    for text in ("Agent", "Agency Starter", "Agency Pro", "$29", "$99", "$249", "$10", "$25"):
        assert text in html, text
    client.force_login(agent)
    assert client.get(reverse("billing:account")).status_code == 200


def test_admin_payments_and_revenue(client, make_user, landlord):
    Purchase.objects.create(user=landlord, kind=Purchase.Kind.FEATURED, description="f", amount=Decimal("25"), currency="USD",
                            status=Purchase.Status.PAID, paid_at=timezone.now(), payment_intent_id="pi_live")
    client.force_login(make_user(is_staff=True))
    page = client.get(reverse("staff:payments"))
    assert page.status_code == 200 and page.context["summary"]["revenue_month"] == Decimal("25")
    assert "dashboard.stripe.com/test/payments/pi_live" in page.content.decode()
    assert client.get(reverse("staff:overview")).context["metrics"]["revenue_month"] == Decimal("25")


def test_cancel_local_demo_plan_message(client, agent):
    Subscription.objects.create(user=agent, plan=Plan.objects.get(code="agent"), status="active")
    client.force_login(agent)
    response = client.post(reverse("billing:cancel"), follow=True)
    assert "has been cancelled" in response.content.decode()
    assert not Subscription.objects.get().grants_access
