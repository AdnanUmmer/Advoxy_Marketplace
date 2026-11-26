from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.gis.measure import D
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.permissions import LISTER_ROLES, role_required, verified_email_required

from . import photos as photo_ops
from . import rules
from .forms import ListingForm
from .models import Listing, ListingStatus, Purpose


def mapbox_token():
    """The public Mapbox token, or '' when not configured (forms fall back to coordinates)."""
    token = settings.MAPBOX_TOKEN or ""
    return token if token.startswith("pk.") and "your-" not in token else ""


def lister_required(view):
    """Signed in, verified email, and a role that can list properties."""
    return verified_email_required(role_required(*LISTER_ROLES)(view))


def owned_listing(view):
    """Load the listing from `pk` and 404 unless the current user owns it."""

    @wraps(view)
    def wrapped(request, pk, *args, **kwargs):
        listing = get_object_or_404(Listing, pk=pk, owner=request.user)
        return view(request, listing, *args, **kwargs)

    return lister_required(wrapped)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------
def similar_listings(listing, limit=4):
    base = (
        Listing.objects.published()
        .exclude(pk=listing.pk)
        .filter(purpose=listing.purpose)
        .prefetch_related("photos")
    )
    low, high = listing.price * Decimal("0.6"), listing.price * Decimal("1.6")
    location = getattr(listing, "location", None)
    picks = []
    if location:
        nearby = base.filter(location__point__dwithin=(location.point, D(km=30)), price__range=(low, high))
        picks = list(nearby.order_by("-published_at")[:limit])
    if len(picks) < limit:
        more = base.filter(city=listing.city).exclude(pk__in=[p.pk for p in picks]).order_by("-published_at")
        picks += list(more[: limit - len(picks)])
    return picks


GALLERY_LAYOUTS = {
    # photos shown -> classes per tile on the 4x2 desktop grid (first tile is the cover)
    1: ["sm:col-span-4 sm:row-span-2"],
    2: ["sm:col-span-2 sm:row-span-2"] * 2,
    3: ["sm:col-span-2 sm:row-span-2", "sm:row-span-2", "sm:row-span-2"],
    4: ["sm:col-span-2 sm:row-span-2", "sm:row-span-2", "", ""],
    5: ["sm:col-span-2 sm:row-span-2", "", "", "", ""],
}


def gallery_tiles(photos):
    shown = photos[:5]
    return list(zip(shown, GALLERY_LAYOUTS.get(len(shown), [])))


def detail(request, pk, slug):
    listing = get_object_or_404(
        Listing.objects.select_related("owner", "owner__profile", "location", "agency")
        .prefetch_related("photos", "amenities"),
        pk=pk,
    )
    is_owner = request.user.is_authenticated and listing.owner_id == request.user.pk
    if listing.status != ListingStatus.PUBLISHED and not (is_owner or request.user.is_staff):
        raise Http404
    if slug != listing.slug:
        return redirect(listing, permanent=True)
    agent_profile = getattr(listing.owner, "agent_profile", None) if listing.owner.is_agent else None
    photos = list(listing.photos.all())
    context = {
        "listing": listing,
        "photos": photos,
        "tiles": gallery_tiles(photos),
        "is_owner": is_owner,
        "preview": listing.status != ListingStatus.PUBLISHED,
        "agent_profile": agent_profile,
        "similar": similar_listings(listing) if listing.status == ListingStatus.PUBLISHED else [],
        "mapbox_token": mapbox_token(),
    }
    from apps.messaging.models import Thread
    from apps.messaging.views import inquiry_form_for

    context["inquiry_form"] = inquiry_form_for(request.user, listing)
    context["existing_thread"] = (
        Thread.objects.filter(listing=listing, buyer=request.user).first() if request.user.is_authenticated else None
    )
    return render(request, "listings/detail.html", context)


# ---------------------------------------------------------------------------
# Owner: create / edit
# ---------------------------------------------------------------------------
def featured_until(listing):
    from django.db.models import Max

    from apps.billing.models import FeaturedPlacement

    return FeaturedPlacement.objects.active().filter(listing=listing).aggregate(m=Max("ends_at"))["m"] if listing.is_featured else None


@lister_required
def create(request):
    form = ListingForm(request.POST or None, request.FILES or None, currency_code=settings.CURRENCY_CODE)
    if request.method == "POST" and form.is_valid():
        files = form.cleaned_data.get("photos") or []
        with transaction.atomic():
            listing = form.save(commit=False)
            listing.owner = request.user
            agent_profile = getattr(request.user, "agent_profile", None)
            owned_agency = getattr(request.user, "owned_agency", None) if request.user.is_agency else None
            if owned_agency:
                listing.agency_id = owned_agency.pk
            elif agent_profile and agent_profile.agency_id:
                listing.agency_id = agent_profile.agency_id
            listing.status = ListingStatus.DRAFT
            listing.save()
            form.save_m2m()
            form.save_location(listing)
            saved, errors = photo_ops.add_photos(listing, files) if files else ([], [])
        for err in errors:
            messages.error(request, err)
        messages.success(request, _("Draft saved. Add photos and submit it for review when you're ready."))
        return redirect("listings:edit", pk=listing.pk)
    return render(request, "listings/form.html", {
        "form": form, "mapbox_token": mapbox_token(), "capacity": rules.capacity_for(request.user),
    })


@owned_listing
def edit(request, listing):
    if listing.status in rules.CLOSED_STATUSES and listing.status != ListingStatus.EXPIRED:
        messages.info(request, _("Closed listings can't be edited."))
        return redirect("listings:mine")
    form = ListingForm(request.POST or None, instance=listing, currency_code=settings.CURRENCY_CODE)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            listing = form.save(commit=False)
            listing.slug = slugify(listing.title)[:150] or "listing"
            sent_back = form.has_changed() and rules.mark_edited(listing)
            listing.save()
            form.save_m2m()
            form.save_location(listing)
        if sent_back:
            messages.info(request, _("Changes saved. Your listing goes back to review before the changes go live."))
        else:
            messages.success(request, _("Changes saved."))
        return redirect("listings:edit", pk=listing.pk)
    return render(request, "listings/form.html", {
        "form": form,
        "listing": listing,
        "mapbox_token": mapbox_token(),
        "capacity": rules.capacity_for(request.user),
        "actions": rules.available_owner_actions(listing),
        "missing": rules.missing_for_review(listing),
        "max_photos": rules.MAX_PHOTOS,
        "featured_until": featured_until(listing),
        "featured_price": settings.FEATURED_PRICE,
        "featured_days": settings.FEATURED_DAYS,
    })


@require_POST
@owned_listing
def transition(request, listing, action):
    try:
        rules.owner_transition(listing, request.user, action)
    except rules.TransitionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, {
            "submit": _("Submitted. Our team reviews listings within one working day."),
            "withdraw": _("Moved back to drafts."),
            "mark_sold": _("Marked as sold. Congratulations!"),
            "mark_rented": _("Marked as rented."),
            "remove": _("Listing removed."),
        }[action])
    nxt = request.POST.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect("listings:mine")


# ---------------------------------------------------------------------------
# Owner: photos (HTMX partial)
# ---------------------------------------------------------------------------
def _photo_panel(request, listing, errors=None):
    return render(request, "listings/_photo_manager.html", {
        "listing": listing, "photos": list(listing.photos.all()), "errors": errors or [], "max_photos": rules.MAX_PHOTOS,
    })


@require_POST
@owned_listing
def photo_upload(request, listing):
    files = request.FILES.getlist("photos")
    if not files:
        return _photo_panel(request, listing, [_("Choose at least one photo.")])
    _saved, errors = photo_ops.add_photos(listing, files)
    return _photo_panel(request, listing, errors)


@require_POST
@owned_listing
def photo_action(request, listing, photo_id, op):
    if op == "delete":
        photo_ops.delete_photo(listing, photo_id)
    elif op in ("up", "down"):
        photo_ops.move(listing, photo_id, -1 if op == "up" else 1)
    elif op == "cover":
        photo_ops.make_cover(listing, photo_id)
    else:
        return HttpResponseBadRequest()
    if not request.htmx:
        return redirect(reverse("listings:edit", args=[listing.pk]) + "#photos")
    return _photo_panel(request, listing)


@require_POST
@owned_listing
def photo_reorder(request, listing):
    photo_ops.reorder(listing, request.POST.getlist("order"))
    return _photo_panel(request, listing)


# ---------------------------------------------------------------------------
# Owner dashboard: my listings
# ---------------------------------------------------------------------------
STATUS_TABS = [
    ("all", gettext_lazy("All"), None),
    ("draft", gettext_lazy("Drafts"), (ListingStatus.DRAFT,)),
    ("review", gettext_lazy("In review"), (ListingStatus.PENDING,)),
    ("live", gettext_lazy("Live"), (ListingStatus.PUBLISHED,)),
    ("closed", gettext_lazy("Closed"), rules.CLOSED_STATUSES),
]


def owner_dashboard_context(request, user):
    """Listing management panel for the owner/agent dashboards."""
    qs = Listing.objects.filter(owner=user).prefetch_related("photos").order_by("-updated_at")
    counts = {key: (qs.filter(status__in=statuses).count() if statuses else qs.count()) for key, _l, statuses in STATUS_TABS}
    tab = request.GET.get("tab", "all")
    statuses = dict((k, s) for k, _l, s in STATUS_TABS).get(tab)
    if tab not in counts:
        tab = "all"
    rows = qs.filter(status__in=statuses) if statuses else qs
    return {
        "capacity": rules.capacity_for(user),
        "tabs": [(k, label, counts[k]) for k, label, _s in STATUS_TABS],
        "active_tab": tab,
        "rows": [(listing, rules.available_owner_actions(listing)) for listing in rows],
    }


@lister_required
def mine(request):
    return redirect(reverse("accounts:dashboard") + "?" + request.GET.urlencode())
