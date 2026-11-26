"""Stripe implementation of the payment adapter (Checkout + Billing)."""

import stripe
from django.conf import settings

from .base import (
    CheckoutRequest,
    CheckoutResult,
    NormalizedEvent,
    PaymentError,
    PaymentProvider,
    WebhookVerificationError,
)


def _get(obj, *path, default=None):
    """Safe nested lookup on Stripe objects/dicts."""
    cur = obj
    for key in path:
        if cur is None:
            return default
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return default
    return cur if cur is not None else default


def _id(value):
    """Expandable field: string id or expanded object."""
    if value is None:
        return ""
    return value if isinstance(value, str) else _get(value, "id", default="")


def subscription_snapshot(sub):
    """The fields we store, read from a Stripe Subscription (current and older API shapes)."""
    period_end = _get(sub, "items", "data", 0, "current_period_end") or _get(sub, "current_period_end")
    return {
        "subscription_id": _get(sub, "id", default=""),
        "customer_id": _id(_get(sub, "customer")),
        "status": _get(sub, "status", default="incomplete"),
        "current_period_end": period_end,
        "cancel_at_period_end": bool(_get(sub, "cancel_at_period_end", default=False)),
        "metadata": dict(_get(sub, "metadata", default={}) or {}),
    }


def invoice_snapshot(inv, sub_id=None):
    sub_id = sub_id or (_get(inv, "parent", "subscription_details", "subscription") or _get(inv, "subscription"))
    return {
        "invoice_id": _get(inv, "id", default=""),
        "subscription_id": _id(sub_id),
        "amount_cents": _get(inv, "amount_paid", default=0),
        "currency": _get(inv, "currency", default="usd"),
        "period_end": _get(inv, "lines", "data", 0, "period", "end"),
        "metadata": dict(_get(inv, "parent", "subscription_details", "metadata", default={}) or {}),
    }


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(self, secret_key=None, webhook_secret=None):
        self.secret_key = secret_key if secret_key is not None else settings.STRIPE_SECRET_KEY
        self.webhook_secret = webhook_secret if webhook_secret is not None else settings.STRIPE_WEBHOOK_SECRET

    @property
    def test_mode(self):
        return self.secret_key.startswith("sk_test_")

    # --- checkout ---------------------------------------------------------
    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        price_data = {
            "currency": request.currency.lower(),
            "unit_amount": request.item.amount_cents,
            "product_data": {"name": request.item.name, **({"description": request.item.description} if request.item.description else {})},
        }
        if request.mode == "subscription":
            price_data["recurring"] = {"interval": request.interval}
        params = {
            "mode": request.mode,
            "line_items": [{"price_data": price_data, "quantity": 1}],
            "customer_email": request.customer_email,
            "client_reference_id": request.reference,
            "metadata": request.metadata,
            "success_url": request.success_url + ("&" if "?" in request.success_url else "?") + "session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": request.cancel_url,
        }
        if request.mode == "subscription":
            params["subscription_data"] = {"metadata": request.metadata}
        else:
            params["payment_intent_data"] = {"metadata": request.metadata}
        try:
            session = stripe.checkout.Session.create(api_key=self.secret_key, **params)
        except stripe.StripeError as exc:
            raise PaymentError(str(exc.user_message or exc)) from exc
        return CheckoutResult(session_id=session.id, url=session.url)

    def fetch_checkout(self, session_id):
        try:
            session = stripe.checkout.Session.retrieve(
                session_id, api_key=self.secret_key, expand=["subscription", "subscription.latest_invoice"])
        except stripe.StripeError as exc:
            raise PaymentError(str(exc.user_message or exc)) from exc
        return self._normalize_checkout("fetch:" + session_id, session)

    # --- webhooks -----------------------------------------------------------
    def handle_webhook(self, payload: bytes, signature: str) -> NormalizedEvent:
        if not self.webhook_secret:
            raise WebhookVerificationError("Webhook secret is not configured.")
        try:
            event = stripe.Webhook.construct_event(payload, signature or "", self.webhook_secret)
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise WebhookVerificationError(str(exc)) from exc
        return self.normalize(event)

    def normalize(self, event) -> NormalizedEvent:
        etype, obj = _get(event, "type"), _get(event, "data", "object")
        eid = _get(event, "id", default="")
        if etype in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            return self._normalize_checkout(eid, obj)
        if etype in ("customer.subscription.created", "customer.subscription.updated"):
            return NormalizedEvent(eid, "subscription.updated", subscription_snapshot(obj))
        if etype == "customer.subscription.deleted":
            return NormalizedEvent(eid, "subscription.deleted", subscription_snapshot(obj))
        if etype == "invoice.paid":
            sub_id = (_get(obj, "parent", "subscription_details", "subscription")
                      or _get(obj, "subscription") or _get(obj, "lines", "data", 0, "parent", "subscription_item_details", "subscription"))
            return NormalizedEvent(eid, "invoice.paid", invoice_snapshot(obj, sub_id))
        if etype == "charge.refunded":
            return NormalizedEvent(eid, "payment.refunded", {"payment_intent_id": _id(_get(obj, "payment_intent"))})
        return NormalizedEvent(eid, "ignored", {"type": etype})

    def _normalize_checkout(self, eid, session):
        sub = _get(session, "subscription")
        data = {
            "session_id": _get(session, "id", default=""),
            "mode": _get(session, "mode"),
            "paid": _get(session, "payment_status") in ("paid", "no_payment_required"),
            "status": _get(session, "status"),
            "reference": _get(session, "client_reference_id", default=""),
            "metadata": dict(_get(session, "metadata", default={}) or {}),
            "payment_intent_id": _id(_get(session, "payment_intent")),
            "customer_id": _id(_get(session, "customer")),
            "subscription": subscription_snapshot(sub) if sub and not isinstance(sub, str) else None,
            "subscription_id": _id(sub),
            "invoice": None,
        }
        invoice = _get(sub, "latest_invoice") if sub and not isinstance(sub, str) else None
        if invoice and not isinstance(invoice, str) and _get(invoice, "status") == "paid":
            data["invoice"] = invoice_snapshot(invoice, _id(sub))
        return NormalizedEvent(eid, "checkout.completed", data)

    # --- subscriptions --------------------------------------------------------
    def cancel_subscription(self, provider_subscription_id, at_period_end=True):
        try:
            if at_period_end:
                sub = stripe.Subscription.modify(provider_subscription_id, cancel_at_period_end=True, api_key=self.secret_key)
            else:
                sub = stripe.Subscription.cancel(provider_subscription_id, api_key=self.secret_key)
        except stripe.StripeError as exc:
            raise PaymentError(str(exc.user_message or exc)) from exc
        return subscription_snapshot(sub)

    def resume_subscription(self, provider_subscription_id):
        try:
            sub = stripe.Subscription.modify(provider_subscription_id, cancel_at_period_end=False, api_key=self.secret_key)
        except stripe.StripeError as exc:
            raise PaymentError(str(exc.user_message or exc)) from exc
        return subscription_snapshot(sub)

    def dashboard_url(self, kind, provider_id):
        if not provider_id:
            return ""
        base = "https://dashboard.stripe.com/" + ("test/" if self.test_mode else "")
        return base + {"payment": "payments/", "subscription": "subscriptions/", "invoice": "invoices/"}.get(kind, "") + provider_id
