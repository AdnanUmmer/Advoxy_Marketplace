from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.models import AgencyTeam, AgentProfile, Role, User, VerificationStatus
from apps.accounts.permissions import role_required, verified_email_required
from apps.listings.models import Listing, ListingStatus

from . import services
from .models import AgencyInvitation

PUBLISHED = Q(user__listings__status=ListingStatus.PUBLISHED)


def _verified_first(field="verification_status"):
    return Case(When(**{field: VerificationStatus.VERIFIED}, then=Value(0)), default=Value(1), output_field=IntegerField())


# ---------------------------------------------------------------------------
# Public directory
# ---------------------------------------------------------------------------
def agents(request):
    qs = (
        AgentProfile.objects.filter(user__is_agent=True, user__is_active=True, user__is_suspended=False)
        .select_related("user", "user__profile", "agency")
        .annotate(live=Count("user__listings", filter=PUBLISHED, distinct=True), vrank=_verified_first())
    )
    g = request.GET
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(user__full_name__icontains=q) | Q(specialties__icontains=q) | Q(agency__name__icontains=q))
    if g.get("city"):
        qs = qs.filter(Q(user__profile__city__iexact=g["city"]) | Q(user__listings__city__iexact=g["city"])).distinct()
    if g.get("agency"):
        qs = qs.filter(agency__slug=g["agency"])
    if g.get("verified") == "1":
        qs = qs.filter(verification_status=VerificationStatus.VERIFIED)
    qs = qs.order_by("vrank", "-live", "user__full_name")
    page = Paginator(qs, 24).get_page(g.get("page"))
    cities = (Listing.objects.published().filter(owner__is_agent=True).order_by("city").values_list("city", flat=True).distinct())
    return render(request, "agencies/agents.html", {
        "page": page, "agencies": AgencyTeam.objects.order_by("name"), "cities": cities,
        "filtered": any(g.get(k) for k in ("q", "city", "agency", "verified")),
    })


def agent_detail(request, pk):
    agent_user = get_object_or_404(User.objects.select_related("profile"), pk=pk, is_agent=True, is_active=True, is_suspended=False)
    profile = getattr(agent_user, "agent_profile", None)
    if profile is None:
        raise Http404
    listings = Listing.objects.published().filter(owner=agent_user).prefetch_related("photos").order_by("-is_featured", "-published_at")
    page = Paginator(listings, 12).get_page(request.GET.get("page"))
    stats = {
        "live": listings.count(),
        "sold": Listing.objects.filter(owner=agent_user, status__in=(ListingStatus.SOLD, ListingStatus.RENTED)).count(),
        "cities": sorted(set(listings.values_list("city", flat=True))),
    }
    return render(request, "agencies/agent_detail.html", {"agent": agent_user, "profile": profile, "page": page, "stats": stats})


def agencies(request):
    qs = (
        AgencyTeam.objects.filter(owner__is_active=True, owner__is_suspended=False)
        .annotate(agent_count=Count("agents", distinct=True),
                  live=Count("listings", filter=Q(listings__status=ListingStatus.PUBLISHED), distinct=True),
                  vrank=_verified_first())
        .order_by("vrank", "-live", "name")
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(city__icontains=q) | Q(country__icontains=q))
    return render(request, "agencies/agencies.html", {"agencies": qs, "q": q})


def agency_detail(request, slug):
    agency = get_object_or_404(AgencyTeam.objects.select_related("owner"), slug=slug, owner__is_active=True, owner__is_suspended=False)
    team = (agency.agents.filter(user__is_active=True, user__is_suspended=False).select_related("user", "user__profile")
            .annotate(live=Count("user__listings", filter=PUBLISHED, distinct=True), vrank=_verified_first())
            .order_by("vrank", "-live", "user__full_name"))
    listings = agency.listings.published().prefetch_related("photos").order_by("-is_featured", "-published_at")
    page = Paginator(listings, 12).get_page(request.GET.get("page"))
    return render(request, "agencies/agency_detail.html", {
        "agency": agency, "team": team, "page": page, "live_count": listings.count(),
        "cities": sorted(set(listings.values_list("city", flat=True))),
    })


# ---------------------------------------------------------------------------
# Team management (agency owner) and invitations (agents)
# ---------------------------------------------------------------------------
@role_required(Role.AGENCY)
def team(request):
    agency = getattr(request.user, "owned_agency", None)
    if agency is None:
        raise Http404
    members = (agency.agents.select_related("user")
               .annotate(live=Count("user__listings", filter=PUBLISHED, distinct=True)).order_by("user__full_name"))
    return render(request, "agencies/team.html", {
        "agency": agency, "members": members, "invitations": services.open_invitations(agency),
        "seats": services.seat_limit(agency), "used": services.seats_used(agency),
    })


@require_POST
@verified_email_required
@role_required(Role.AGENCY)
def team_invite(request):
    agency = getattr(request.user, "owned_agency", None)
    if agency is None:
        raise Http404
    email = request.POST.get("email", "").strip()
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    try:
        validate_email(email)
        services.invite(agency, request.user, email)
    except ValidationError:
        messages.error(request, _("Enter a valid email address."))
    except services.TeamError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("Invitation sent to %(email)s.") % {"email": email})
    return redirect("agencies:team")


@require_POST
@role_required(Role.AGENCY)
def team_revoke(request, pk):
    inv = get_object_or_404(AgencyInvitation, pk=pk, agency__owner=request.user)
    services.revoke(inv, request.user)
    messages.success(request, _("Invitation revoked."))
    return redirect("agencies:team")


@require_POST
@role_required(Role.AGENCY)
def team_remove(request, pk):
    member = get_object_or_404(AgentProfile, pk=pk, agency__owner=request.user)
    services.detach(member.user, request.user)
    messages.success(request, _("%(name)s was removed from the team. Their listings stay with them.") % {"name": member.user.full_name})
    return redirect("agencies:team")


@require_POST
@role_required(Role.AGENT)
def team_leave(request):
    try:
        agency = services.detach(request.user, request.user)
    except services.TeamError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("You left %(agency)s.") % {"agency": agency.name})
    return redirect("accounts:dashboard")


def invitation(request, token):
    inv = get_object_or_404(AgencyInvitation.objects.select_related("agency"), token=token)
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect(f"{reverse_login()}?next={request.path}")
        try:
            if request.POST.get("decision") == "accept":
                services.accept(inv, request.user)
                messages.success(request, _("Welcome to %(agency)s.") % {"agency": inv.agency.name})
                return redirect("accounts:dashboard")
            services.decline(inv, request.user)
            messages.info(request, _("Invitation declined."))
            return redirect("accounts:dashboard")
        except services.TeamError as exc:
            messages.error(request, str(exc))
    wrong_account = request.user.is_authenticated and request.user.email.lower() != inv.email.lower()
    return render(request, "agencies/invitation.html", {"inv": inv, "wrong_account": wrong_account})


def reverse_login():
    from django.urls import reverse

    return reverse("accounts:login")
