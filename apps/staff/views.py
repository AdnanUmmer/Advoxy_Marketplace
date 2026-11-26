"""Staff admin dashboard (SPEC section 6): overview, moderation, listings, users, verifications."""

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts import verification
from apps.accounts.models import ROLE_FIELDS, Role, User, VerificationDocument, VerificationStatus
from apps.accounts.permissions import staff_required
from apps.core.emails import send_templated_email
from apps.listings import rules
from apps.listings.models import Listing, ListingStatus, PropertyType, Purpose
from apps.messaging.models import Inquiry

from .tables import Table


def nav_counts():
    return {
        "pending_listings": Listing.objects.filter(status=ListingStatus.PENDING).count(),
        "pending_verifications": VerificationDocument.objects.filter(status=VerificationDocument.Status.PENDING).count(),
    }


def render_staff(request, template, context=None, partial=None):
    """Full page normally; just the table region for HTMX requests."""
    ctx = {"nav": nav_counts(), "per_page_options": (25, 50, 100), **(context or {})}
    if partial and request.htmx and not request.htmx.boosted:
        return render(request, partial, ctx)
    return render(request, template, ctx)


def _back(request, fallback):
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/staff/") else fallback)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
def daily_series(queryset, field, days=30):
    """[{date, count}] for the last `days` days, zero-filled."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    rows = (
        queryset.filter(**{f"{field}__date__gte": start})
        .annotate(day=TruncDate(field))
        .values("day")
        .annotate(n=Count("id"))
    )
    counts = {r["day"]: r["n"] for r in rows}
    series = [{"date": start + timedelta(days=i), "count": counts.get(start + timedelta(days=i), 0)} for i in range(days)]
    peak = max([p["count"] for p in series] + [1])
    for p in series:
        p["pct"] = round(100 * p["count"] / peak, 1)
    return series, peak, sum(p["count"] for p in series)


@staff_required
def overview(request):
    now = timezone.now()
    week_ago, two_weeks_ago = now - timedelta(days=7), now - timedelta(days=14)
    listings = Listing.objects.all()
    status_counts = dict(listings.values_list("status").annotate(n=Count("id")))
    members = User.objects.filter(is_active=True, is_suspended=False)
    roles = [(role, members.filter(**{ROLE_FIELDS[role]: True}).count()) for role in Role if role != Role.ADMIN]
    inquiries_week = Inquiry.objects.filter(created_at__gte=week_ago).count()
    inquiries_prev = Inquiry.objects.filter(created_at__gte=two_weeks_ago, created_at__lt=week_ago).count()
    listing_series, listing_peak, listing_total = daily_series(listings, "created_at")
    inquiry_series, inquiry_peak, inquiry_total = daily_series(Inquiry.objects.all(), "created_at")

    activity = []
    for u in User.objects.order_by("-date_joined")[:6]:
        activity.append({"when": u.date_joined, "kind": "signup", "text": _("%(name)s joined") % {"name": u.full_name},
                         "url": reverse("staff:user_detail", args=[u.pk])})
    for l in listings.filter(status=ListingStatus.PENDING).select_related("owner").order_by("-updated_at")[:6]:
        activity.append({"when": l.updated_at, "kind": "review", "text": _("%(title)s submitted for review") % {"title": l.title},
                         "url": reverse("staff:moderation") + f"#listing-{l.pk}"})
    for i in Inquiry.objects.select_related("listing").order_by("-created_at")[:6]:
        activity.append({"when": i.created_at, "kind": "inquiry", "text": _("%(name)s asked about %(title)s") % {"name": i.name, "title": i.listing.title},
                         "url": i.listing.get_absolute_url()})
    for d in VerificationDocument.objects.select_related("user").order_by("-created_at")[:6]:
        activity.append({"when": d.created_at, "kind": "verification", "text": _("%(name)s uploaded a license") % {"name": d.user.full_name},
                         "url": reverse("staff:verifications")})
    activity.sort(key=lambda a: a["when"], reverse=True)

    context = {
        "metrics": {
            "listings_total": listings.exclude(status=ListingStatus.REMOVED).count(),
            "published": status_counts.get(ListingStatus.PUBLISHED, 0),
            "pending": status_counts.get(ListingStatus.PENDING, 0),
            "users_total": members.count(),
            "new_users_week": members.filter(date_joined__gte=week_ago).count(),
            "inquiries_week": inquiries_week,
            "inquiries_delta": inquiries_week - inquiries_prev,
        },
        "roles": roles,
        "roles_peak": max([n for _r, n in roles] + [1]),
        "status_rows": [(s, s.label, status_counts.get(s, 0)) for s in ListingStatus],
        "listing_series": listing_series, "listing_peak": listing_peak, "listing_total": listing_total,
        "inquiry_series": inquiry_series, "inquiry_peak": inquiry_peak, "inquiry_total": inquiry_total,
        "activity": activity[:12],
    }
    return render_staff(request, "staff/overview.html", context)


# ---------------------------------------------------------------------------
# Moderation queue
# ---------------------------------------------------------------------------
def moderate_and_notify(listing, staff_user, decision, note=""):
    listing = rules.moderate(listing, staff_user, decision, note)
    owner = listing.owner
    if decision == "approve":
        name, ctx = "listing_approved", {"path": listing.get_absolute_url()}
    else:
        name, ctx = "listing_rejected", {"path": reverse("listings:edit", args=[listing.pk]), "note": listing.moderation_note,
                                         "changes_requested": decision == "request_edits"}
    ctx.update({"user_name": owner.get_short_name(), "listing_title": listing.title})
    transaction.on_commit(lambda: send_templated_email(name, owner.email, ctx))
    return listing


@staff_required
def moderation(request):
    queue = (
        Listing.objects.filter(status=ListingStatus.PENDING)
        .select_related("owner", "agency", "location")
        .prefetch_related("photos", "amenities")
        .order_by("updated_at")  # oldest first: first in, first reviewed
    )
    return render_staff(request, "staff/moderation.html", {"queue": queue})


@require_POST
@staff_required
def moderation_action(request, pk):
    listing = get_object_or_404(Listing, pk=pk)
    decision = request.POST.get("decision", "")
    try:
        moderate_and_notify(listing, request.user, decision, request.POST.get("note", ""))
    except rules.TransitionError as exc:
        messages.error(request, str(exc))
    else:
        label = {"approve": _("approved"), "reject": _("rejected"), "request_edits": _("sent back for changes")}[decision]
        messages.success(request, _("“%(title)s” %(label)s.") % {"title": listing.title, "label": label})
    return _back(request, reverse("staff:moderation"))


@require_POST
@staff_required
def moderation_bulk_approve(request):
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    done = 0
    for listing in Listing.objects.filter(pk__in=ids, status=ListingStatus.PENDING):
        moderate_and_notify(listing, request.user, "approve")
        done += 1
    messages.success(request, _("Approved %(n)s listings.") % {"n": done})
    return redirect("staff:moderation")


# ---------------------------------------------------------------------------
# Listings table
# ---------------------------------------------------------------------------
LISTING_COLUMNS = {"title": "title", "city": "city", "price": "price", "status": "status", "owner": "owner__full_name",
                   "created": "created_at", "updated": "updated_at"}
BULK_ACTIONS = {
    "feature": gettext_lazy("Feature"),
    "unfeature": gettext_lazy("Remove featured"),
    "unpublish": gettext_lazy("Unpublish"),
    "delete": gettext_lazy("Delete permanently"),
}


@staff_required
def listings(request):
    qs = Listing.objects.select_related("owner", "agency").prefetch_related("photos")
    g = request.GET
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(city__icontains=q) | Q(neighborhood__icontains=q)
                       | Q(owner__email__icontains=q) | Q(owner__full_name__icontains=q) | Q(pk=int(q) if q.isdigit() else -1))
    if g.get("status") in ListingStatus.values:
        qs = qs.filter(status=g["status"])
    if g.get("purpose") in Purpose.values:
        qs = qs.filter(purpose=g["purpose"])
    if g.get("type") in PropertyType.values:
        qs = qs.filter(property_type=g["type"])
    if g.get("country"):
        qs = qs.filter(country=g["country"])
    if g.get("featured") == "1":
        qs = qs.filter(is_featured=True)
    table = Table(request, qs, LISTING_COLUMNS, default="-created")
    context = {
        "table": table,
        "statuses": ListingStatus.choices, "purposes": Purpose.choices, "types": PropertyType.choices,
        "countries": Listing.objects.order_by("country").values_list("country", flat=True).distinct(),
        "bulk_actions": BULK_ACTIONS.items(),
        "filtered": any(g.get(k) for k in ("q", "status", "purpose", "type", "country", "featured")),
    }
    return render_staff(request, "staff/listings.html", context, partial="staff/_listings_table.html")


@require_POST
@staff_required
def listings_bulk(request):
    action = request.POST.get("action")
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    qs = Listing.objects.filter(pk__in=ids)
    if action not in BULK_ACTIONS or not ids:
        messages.error(request, _("Choose listings and an action."))
        return _back(request, reverse("staff:listings"))
    if action == "delete" and request.POST.get("confirm") != "DELETE":
        messages.error(request, _("Type DELETE to confirm permanent deletion."))
        return _back(request, reverse("staff:listings"))
    now = timezone.now()
    if action == "feature":
        n = qs.filter(status=ListingStatus.PUBLISHED).update(is_featured=True, updated_at=now)
    elif action == "unfeature":
        n = qs.update(is_featured=False, updated_at=now)
    elif action == "unpublish":
        n = qs.filter(status__in=(ListingStatus.PUBLISHED, ListingStatus.PENDING)).update(
            status=ListingStatus.DRAFT, is_featured=False, updated_at=now,
            moderation_note=_("Unpublished by our team. Contact support or edit and resubmit."))
    else:
        n, _detail = qs.delete()
        n = len(ids)
    messages.success(request, _("%(action)s: %(n)s listings updated.") % {"action": BULK_ACTIONS[action], "n": n})
    return _back(request, reverse("staff:listings"))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
USER_COLUMNS = {"name": "full_name", "email": "email", "joined": "date_joined", "listings": "listing_count"}
EDITABLE_ROLES = [r for r in Role if r != Role.ADMIN]


@staff_required
def users(request):
    qs = User.objects.annotate(listing_count=Count("listings", distinct=True)).select_related(
        "agent_profile", "owned_agency")
    g = request.GET
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q))
    if g.get("role") in [r.value for r in Role]:
        qs = qs.filter(**{ROLE_FIELDS[Role(g["role"])]: True})
    if g.get("state") == "suspended":
        qs = qs.filter(is_suspended=True)
    elif g.get("state") == "unverified":
        qs = qs.filter(email_verified_at__isnull=True)
    table = Table(request, qs, USER_COLUMNS, default="-joined")
    context = {"table": table, "roles": list(Role), "filtered": any(g.get(k) for k in ("q", "role", "state"))}
    return render_staff(request, "staff/users.html", context, partial="staff/_users_table.html")


@staff_required
def user_detail(request, pk):
    member = get_object_or_404(User.objects.select_related("profile"), pk=pk)
    context = {
        "member": member,
        "agent_profile": getattr(member, "agent_profile", None),
        "agency": getattr(member, "owned_agency", None),
        "member_listings": member.listings.order_by("-updated_at")[:10],
        "documents": member.verification_documents.all()[:5],
        "editable_roles": [(r, member.has_role(r)) for r in EDITABLE_ROLES],
        "verification_choices": VerificationStatus.choices,
    }
    return render_staff(request, "staff/user_detail.html", context)


@require_POST
@staff_required
def user_action(request, pk, action):
    member = get_object_or_404(User, pk=pk)
    url = reverse("staff:user_detail", args=[pk])
    if member.pk == request.user.pk and action in ("suspend", "roles"):
        messages.error(request, _("You can't change your own account here."))
        return redirect(url)
    if member.is_superuser and not request.user.is_superuser:
        messages.error(request, _("Only a superuser can change a superuser."))
        return redirect(url)
    if action == "suspend":
        member.is_suspended = True
        member.save(update_fields=["is_suspended"])
        messages.success(request, _("%(name)s is suspended and signed out.") % {"name": member.full_name})
    elif action == "unsuspend":
        member.is_suspended = False
        member.save(update_fields=["is_suspended"])
        messages.success(request, _("%(name)s can sign in again.") % {"name": member.full_name})
    elif action == "roles":
        chosen = [Role(r) for r in request.POST.getlist("roles") if r in [x.value for x in EDITABLE_ROLES]]
        if not chosen:
            messages.error(request, _("Keep at least one role."))
            return redirect(url)
        member.set_roles(chosen)
        member.save()
        from apps.accounts.models import AgencyTeam, AgentProfile

        if member.is_agent:
            AgentProfile.objects.get_or_create(user=member)
        if member.is_agency and not hasattr(member, "owned_agency"):
            AgencyTeam.objects.create(owner=member, name=f"{member.full_name} Agency")
        messages.success(request, _("Roles updated."))
    elif action == "verification":
        status = request.POST.get("status")
        if status not in VerificationStatus.values:
            raise Http404
        verification.set_status(member, status)
        messages.success(request, _("Verification status updated."))
    else:
        raise Http404
    return redirect(url)


# ---------------------------------------------------------------------------
# Verifications
# ---------------------------------------------------------------------------
@staff_required
def verifications(request):
    tab = request.GET.get("tab", "pending")
    docs = VerificationDocument.objects.select_related("user", "agency", "reviewed_by", "user__agent_profile")
    docs = docs.filter(status=VerificationDocument.Status.PENDING).order_by("created_at") if tab == "pending" \
        else docs.exclude(status=VerificationDocument.Status.PENDING).order_by("-reviewed_at")[:100]
    return render_staff(request, "staff/verifications.html", {"docs": docs, "tab": tab})


@require_POST
@staff_required
def verification_review(request, pk):
    doc = get_object_or_404(VerificationDocument, pk=pk)
    approve = request.POST.get("decision") == "approve"
    try:
        verification.review_document(doc, request.user, approve, request.POST.get("reason", ""))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("Verification approved.") if approve else _("Verification rejected."))
    return redirect("staff:verifications")


@staff_required
def verification_file(request, pk):
    doc = get_object_or_404(VerificationDocument, pk=pk)
    try:
        handle = doc.document.open("rb")
    except FileNotFoundError:
        raise Http404
    response = FileResponse(handle, as_attachment=False, filename=doc.document.name.rsplit("/", 1)[-1])
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "sandbox"
    return response
