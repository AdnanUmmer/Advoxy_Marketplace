"""
Billing rules. Views start checkouts here; webhooks and the success page both
feed provider events into `apply_event`, which is idempotent, so a payment is
fulfilled exactly once however many times we hear about it.
"""

import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.emails import send_templated_email
from apps.listings.models import Listing, ListingStatus

from .models import FeaturedPlacement, Plan, Purchase, Subscription, WebhookEvent
from .providers import get_provider
from .providers.base import CheckoutRequest, LineItem, PaymentError
from apps.core import site_settings

log = logging.getLogger(__name__)


class BillingError(Exception):
    pass


def _url(path, base_url=None):
    return (base_url or settings.SITE_URL).rstrip("/") + path


def _cents(amount):
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def _ts(value):
    return datetime.fromtimestamp(int(value), tz=dt_timezone.utc) if value else None


# ---------------------------------------------------------------------------
# Capacity helpers (used by listings.rules)
# ---------------------------------------------------------------------------
def active_subscription(user):
    return (
        Subscription.objects.filter(user=user, status__in=Subscription.GRANTS_ACCESS)
        .select_related("plan").order_by("-plan__listing_limit").first()
    )


def plan_scope(user):
    """(plan or None, queryset of listings counted against it).

    Agents in an agency share the agency owner's plan and capacity; independent
    agents and agency owners use their own subscription.
    """
    agent = getattr(user, "agent_profile", None) if user.is_agent else None
    agency = getattr(user, "owned_agency", None) if user.is_agency else None
    if agent and agent.agency_id and not agency:
        agency = agent.agency
    if agency:
        sub = active_subscription(agency.owner)
        if sub:
            return sub.plan, Listing.objects.filter(agency=agency)
    sub = active_subscription(user)
    if sub:
        return sub.plan, Listing.objects.filter(owner=user)
    return None, Listing.objects.filter(owner=user)


def paid_extra_slots(user, now=None):
    now = now or timezone.now()
    return Purchase.objects.filter(user=user, kind=Purchase.Kind.EXTRA_LISTING, status=Purchase.Status.PAID,
                                   expires_at__gt=now).count()


# ---------------------------------------------------------------------------
# Starting checkouts
# ---------------------------------------------------------------------------
def _start(user, purchase, mode, item, metadata, cancel_path, base_url=None):
    request = CheckoutRequest(
        mode=mode,
        item=item,
        customer_email=user.email,
        success_url=_url(reverse("billing:success"), base_url),
        cancel_url=_url(cancel_path, base_url),
        reference=str(user.pk),
        metadata={k: str(v) for k, v in metadata.items()},
        currency=site_settings.get("currency_code"),
    )
    try:
        result = get_provider().create_checkout(request)
    except PaymentError as exc:
        if purchase:
            purchase.status = Purchase.Status.FAILED
            purchase.save(update_fields=["status"])
        raise BillingError(_("We couldn't start the payment: %(error)s") % {"error": exc}) from exc
    if purchase:
        purchase.checkout_session_id = result.session_id
        purchase.save(update_fields=["checkout_session_id"])
    return result.url


def start_extra_listing_checkout(user, base_url=None):
    if not (user.is_seller or user.is_landlord or user.is_agent or user.is_agency):
        raise BillingError(_("Only owners and agents can buy listing slots."))
    from apps.listings.rules import capacity_for

    if capacity_for(user).needs_subscription:
        raise BillingError(_("Agents and agencies need a plan first. Extra slots add to your plan."))
    price, days = site_settings.get("extra_listing_price"), site_settings.get("extra_listing_days")
    desc = _("Extra active listing slot for %(days)s days") % {"days": days}
    purchase = Purchase.objects.create(user=user, kind=Purchase.Kind.EXTRA_LISTING, description=desc,
                                       amount=price, currency=site_settings.get("currency_code"))
    return _start(user, purchase, "payment", LineItem(desc, _cents(price)),
                  {"purchase_id": purchase.pk, "kind": purchase.kind}, reverse("billing:account"), base_url)


def start_featured_checkout(user, listing, base_url=None):
    if listing.owner_id != user.pk:
        raise BillingError(_("You can only feature your own listings."))
    if listing.status != ListingStatus.PUBLISHED:
        raise BillingError(_("Only live listings can be featured."))
    price, days = site_settings.get("featured_price"), site_settings.get("featured_days")
    desc = _("Featured placement for %(days)s days: %(title)s") % {"days": days, "title": listing.title}
    purchase = Purchase.objects.create(user=user, kind=Purchase.Kind.FEATURED, listing=listing, description=desc[:200],
                                       amount=price, currency=site_settings.get("currency_code"))
    return _start(user, purchase, "payment", LineItem(desc[:200], _cents(price)),
                  {"purchase_id": purchase.pk, "kind": purchase.kind, "listing_id": listing.pk},
                  reverse("listings:edit", args=[listing.pk]), base_url)


def start_subscription_checkout(user, plan, base_url=None):
    if not plan.is_active:
        raise BillingError(_("This plan is not available."))
    if plan.audience == Plan.Audience.AGENT and not user.is_agent:
        raise BillingError(_("Agent plans are for agent accounts."))
    if plan.audience == Plan.Audience.AGENCY and not user.is_agency:
        raise BillingError(_("Agency plans are for agency accounts."))
    if active_subscription(user):
        raise BillingError(_("You already have an active plan. Cancel it first to switch."))
    sub = Subscription.objects.create(user=user, plan=plan, status=Subscription.Status.INCOMPLETE)
    item = LineItem(_("%(plan)s plan") % {"plan": plan.name}, _cents(plan.price_monthly), plan.description)
    return _start(user, None, "subscription", item,
                  {"subscription_ref": sub.pk, "plan": plan.code, "user_id": user.pk}, reverse("billing:pricing"), base_url)


def cancel_subscription(sub, at_period_end=True):
    if not sub.provider_subscription_id:
        sub.status = Subscription.Status.CANCELED
        sub.save(update_fields=["status", "updated_at"])
        return sub
    try:
        snap = get_provider(sub.provider).cancel_subscription(sub.provider_subscription_id, at_period_end)
    except PaymentError as exc:
        raise BillingError(_("We couldn't cancel the plan: %(error)s") % {"error": exc}) from exc
    _apply_subscription_snapshot(snap, sub)
    return sub


def resume_subscription(sub):
    try:
        snap = get_provider(sub.provider).resume_subscription(sub.provider_subscription_id)
    except PaymentError as exc:
        raise BillingError(str(exc)) from exc
    _apply_subscription_snapshot(snap, sub)
    return sub


# ---------------------------------------------------------------------------
# Applying provider events (webhooks and success-page lookups)
# ---------------------------------------------------------------------------
@transaction.atomic
def apply_event(event, provider="stripe"):
    """Returns True if the event changed something, False if seen before or ignored."""
    if not event.id.startswith("fetch:"):
        try:
            with transaction.atomic():
                WebhookEvent.objects.create(provider=provider, event_id=event.id, type=event.type)
        except IntegrityError:
            return False  # already processed
    handler = {
        "checkout.completed": _on_checkout_completed,
        "subscription.updated": lambda d: _apply_subscription_snapshot(d),
        "subscription.deleted": lambda d: _apply_subscription_snapshot({**d, "status": "canceled"}),
        "invoice.paid": _on_invoice_paid,
        "payment.refunded": _on_refunded,
    }.get(event.type)
    if handler is None:
        return False
    handler(event.data)
    return True


def _on_checkout_completed(data):
    meta = data.get("metadata") or {}
    if data.get("mode") == "subscription":
        snap = data.get("subscription") or {"subscription_id": data.get("subscription_id"), "status": "active" if data.get("paid") else "incomplete",
                                             "customer_id": data.get("customer_id"), "metadata": meta}
        snap.setdefault("metadata", {}).update(meta)
        _apply_subscription_snapshot(snap)
        if data.get("invoice"):
            _on_invoice_paid({**data["invoice"], "metadata": {**meta, **(data["invoice"].get("metadata") or {})}})
        return
    purchase = Purchase.objects.select_for_update().filter(pk=meta.get("purchase_id")).first() \
        or Purchase.objects.select_for_update().filter(checkout_session_id=data.get("session_id")).first()
    if purchase is None:
        log.warning("Checkout %s has no matching purchase", data.get("session_id"))
        return
    if data.get("paid"):
        fulfil_purchase(purchase, data.get("payment_intent_id", ""))


def _apply_subscription_snapshot(snap, sub=None):
    meta = snap.get("metadata") or {}
    if sub is None:
        sub = Subscription.objects.select_for_update().filter(provider_subscription_id=snap.get("subscription_id")).first() \
            if snap.get("subscription_id") else None
    if sub is None and meta.get("subscription_ref"):
        sub = Subscription.objects.select_for_update().filter(pk=meta["subscription_ref"]).first()
    if sub is None:
        log.warning("Subscription event %s has no local record", snap.get("subscription_id"))
        return None
    was_active = sub.grants_access
    if snap.get("subscription_id"):
        sub.provider_subscription_id = snap["subscription_id"]
    if snap.get("customer_id"):
        sub.provider_customer_id = snap["customer_id"]
    sub.status = snap.get("status") or sub.status
    if snap.get("current_period_end"):
        sub.current_period_end = _ts(snap["current_period_end"])
    sub.cancel_at_period_end = bool(snap.get("cancel_at_period_end", sub.cancel_at_period_end))
    sub.save()
    if sub.grants_access and not was_active:
        Subscription.objects.filter(user=sub.user, status=Subscription.Status.INCOMPLETE).exclude(pk=sub.pk).update(
            status=Subscription.Status.INCOMPLETE_EXPIRED)
    return sub


def _on_invoice_paid(data):
    sub = Subscription.objects.filter(provider_subscription_id=data.get("subscription_id")).select_related("plan", "user").first()         if data.get("subscription_id") else None
    ref = (data.get("metadata") or {}).get("subscription_ref")
    if sub is None and ref:
        sub = Subscription.objects.filter(pk=ref).select_related("plan", "user").first()
        if sub and data.get("subscription_id") and not sub.provider_subscription_id:
            sub.provider_subscription_id = data["subscription_id"]
    if sub is None or not data.get("invoice_id"):
        return
    if Purchase.objects.filter(invoice_id=data["invoice_id"]).exists():
        return
    amount = Decimal(data.get("amount_cents") or 0) / 100
    now = timezone.now()
    purchase = Purchase.objects.create(
        user=sub.user, kind=Purchase.Kind.SUBSCRIPTION, subscription=sub, invoice_id=data["invoice_id"],
        description=_("%(plan)s plan, monthly") % {"plan": sub.plan.name}, amount=amount,
        currency=(data.get("currency") or site_settings.get("currency_code")).upper(), status=Purchase.Status.PAID, paid_at=now,
    )
    if data.get("period_end"):
        sub.current_period_end = _ts(data["period_end"])
    if sub.status in (Subscription.Status.INCOMPLETE, Subscription.Status.PAST_DUE, Subscription.Status.UNPAID):
        sub.status = Subscription.Status.ACTIVE
    sub.save()
    _send_receipt(purchase)


def _on_refunded(data):
    if data.get("payment_intent_id"):
        Purchase.objects.filter(payment_intent_id=data["payment_intent_id"], status=Purchase.Status.PAID).update(
            status=Purchase.Status.REFUNDED)


@transaction.atomic
def fulfil_purchase(purchase, payment_intent_id=""):
    """Mark a one-time purchase paid and grant what it bought. Safe to call twice."""
    purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status == Purchase.Status.PAID:
        return purchase
    now = timezone.now()
    purchase.status = Purchase.Status.PAID
    purchase.paid_at = now
    purchase.payment_intent_id = payment_intent_id or purchase.payment_intent_id
    if purchase.kind == Purchase.Kind.EXTRA_LISTING:
        purchase.expires_at = now + timedelta(days=site_settings.get("extra_listing_days"))
    purchase.save()
    if purchase.kind == Purchase.Kind.FEATURED and purchase.listing_id:
        # Stack after any placement still running, so buying twice extends rather than overlaps.
        current_end = FeaturedPlacement.objects.filter(listing_id=purchase.listing_id, ends_at__gt=now).aggregate(m=Max("ends_at"))["m"]
        start = max(now, current_end) if current_end else now
        FeaturedPlacement.objects.create(listing_id=purchase.listing_id, purchase=purchase, starts_at=start,
                                         ends_at=start + timedelta(days=site_settings.get("featured_days")))
        Listing.objects.filter(pk=purchase.listing_id).update(is_featured=True)
    _send_receipt(purchase)
    return purchase


def end_featured_placements(now=None):
    """Unfeature listings whose paid placements have all ended. Returns how many were unfeatured."""
    now = now or timezone.now()
    ended = FeaturedPlacement.objects.filter(ends_at__lte=now, ended_processed=False)
    listing_ids = set(ended.values_list("listing_id", flat=True))
    ended.update(ended_processed=True)
    still = set(FeaturedPlacement.objects.active(now).filter(listing_id__in=listing_ids).values_list("listing_id", flat=True))
    return Listing.objects.filter(pk__in=listing_ids - still).update(is_featured=False)


def _send_receipt(purchase):
    user = purchase.user
    ctx = {
        "user_name": user.get_short_name(),
        "description": purchase.description,
        "amount": purchase.amount,
        "currency": purchase.currency,
        "paid_at": purchase.paid_at,
        "reference": f"ADV-{purchase.pk:06d}",
        "path": reverse("billing:account"),
    }
    transaction.on_commit(lambda: send_templated_email("payment_receipt", user.email, ctx))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def revenue_between(start, end):
    return Purchase.objects.filter(status=Purchase.Status.PAID, paid_at__gte=start, paid_at__lt=end).aggregate(
        total=Sum("amount"))["total"] or Decimal("0")


def month_start(now=None):
    now = timezone.localtime(now or timezone.now())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def monthly_recurring_revenue():
    return Subscription.objects.filter(status__in=(Subscription.Status.ACTIVE, Subscription.Status.TRIALING)).aggregate(
        total=Sum("plan__price_monthly"))["total"] or Decimal("0")
