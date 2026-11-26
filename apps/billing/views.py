import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import verified_email_required
from apps.listings.models import Listing
from apps.listings.rules import capacity_for

from . import services
from .models import Plan, Purchase, Subscription
from .providers import WebhookVerificationError, get_provider
from .providers.base import PaymentError

log = logging.getLogger(__name__)


def pricing(request):
    plans = Plan.objects.filter(is_active=True)
    return render(request, "billing/pricing.html", {
        "agent_plans": [p for p in plans if p.audience == Plan.Audience.AGENT],
        "agency_plans": [p for p in plans if p.audience == Plan.Audience.AGENCY],
        "extra_price": settings.EXTRA_LISTING_PRICE, "extra_days": settings.EXTRA_LISTING_DAYS,
        "featured_price": settings.FEATURED_PRICE, "featured_days": settings.FEATURED_DAYS,
        "current": services.active_subscription(request.user) if request.user.is_authenticated else None,
    })


@login_required
def account(request):
    user = request.user
    subscription = services.active_subscription(user) or Subscription.objects.filter(
        user=user).exclude(status__in=(Subscription.Status.INCOMPLETE, Subscription.Status.INCOMPLETE_EXPIRED)).first()
    plans = Plan.objects.filter(is_active=True)
    audience = Plan.Audience.AGENCY if user.is_agency else Plan.Audience.AGENT if user.is_agent else None
    context = {
        "subscription": subscription,
        "plans": [p for p in plans if p.audience == audience],
        "capacity": capacity_for(user),
        "can_buy_slots": user.is_seller or user.is_landlord or user.is_agent or user.is_agency,
        "slots": Purchase.objects.filter(user=user, kind=Purchase.Kind.EXTRA_LISTING, status=Purchase.Status.PAID).order_by("-expires_at")[:10],
        "purchases": Purchase.objects.filter(user=user).exclude(status=Purchase.Status.PENDING).select_related("listing")[:50],
        "extra_price": settings.EXTRA_LISTING_PRICE, "extra_days": settings.EXTRA_LISTING_DAYS,
        "now": timezone.now(),
        "agency_plan_shared": user.is_agent and not user.is_agency and getattr(getattr(user, "agent_profile", None), "agency_id", None),
    }
    return render(request, "billing/account.html", context)


def base_url(request):
    """Scheme + host of this request (validated by ALLOWED_HOSTS), for Checkout return URLs."""
    return request.build_absolute_uri("/").rstrip("/")


def _go(request, starter, *args, fallback="billing:account"):
    try:
        return redirect(starter(request.user, *args, base_url=base_url(request)))
    except services.BillingError as exc:
        messages.error(request, str(exc))
        return redirect(fallback)


@require_POST
@verified_email_required
def subscribe(request, code):
    plan = get_object_or_404(Plan, code=code, is_active=True)
    return _go(request, services.start_subscription_checkout, plan, fallback="billing:pricing")


@require_POST
@verified_email_required
def buy_slot(request):
    return _go(request, services.start_extra_listing_checkout)


@require_POST
@verified_email_required
def feature(request, pk):
    listing = get_object_or_404(Listing, pk=pk, owner=request.user)
    try:
        return redirect(services.start_featured_checkout(request.user, listing, base_url=base_url(request)))
    except services.BillingError as exc:
        messages.error(request, str(exc))
        return redirect("listings:edit", pk=listing.pk)


@require_POST
@login_required
def cancel(request):
    sub = services.active_subscription(request.user)
    if not sub:
        messages.info(request, _("You don't have an active plan."))
        return redirect("billing:account")
    try:
        services.cancel_subscription(sub, at_period_end=True)
    except services.BillingError as exc:
        messages.error(request, str(exc))
    else:
        sub.refresh_from_db()
        if not sub.grants_access:
            messages.success(request, _("Your plan has been cancelled."))
            return redirect("billing:account")
        messages.success(request, _("Your plan will end on %(date)s. You keep full access until then.")
                         % {"date": date_format(sub.current_period_end, "j F Y") if sub.current_period_end else _("the end of the period")})
    return redirect("billing:account")


@require_POST
@login_required
def resume(request):
    sub = services.active_subscription(request.user)
    if sub and sub.cancel_at_period_end:
        try:
            services.resume_subscription(sub)
        except services.BillingError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Your plan will continue to renew."))
    return redirect("billing:account")


@login_required
def success(request):
    """Return page from Checkout. Looks the session up so the result shows even before the webhook arrives."""
    session_id = request.GET.get("session_id", "")
    outcome = None
    if session_id:
        try:
            event = get_provider().fetch_checkout(session_id)
        except PaymentError as exc:
            log.warning("Could not fetch checkout %s: %s", session_id, exc)
        else:
            mine = event.data.get("reference") == str(request.user.pk)
            if mine:
                services.apply_event(event)
                outcome = event.data
    purchase = Purchase.objects.filter(checkout_session_id=session_id, user=request.user).select_related("listing").first() if session_id else None
    return render(request, "billing/success.html", {
        "outcome": outcome, "purchase": purchase, "subscription": services.active_subscription(request.user),
    })


@csrf_exempt
@require_POST
def webhook(request, provider):
    """Provider webhooks. The signature is verified before anything is read."""
    try:
        event = get_provider(provider).handle_webhook(request.body, request.headers.get("Stripe-Signature", ""))
    except WebhookVerificationError as exc:
        log.warning("Rejected %s webhook: %s", provider, exc)
        return HttpResponseBadRequest("invalid signature")
    except ValueError:
        return HttpResponseBadRequest("unknown provider")
    services.apply_event(event, provider=provider)  # errors propagate as 500 so the provider retries
    return HttpResponse("ok")
