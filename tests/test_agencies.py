"""Agencies and agents: directory, public profiles, team invitations, seats, joining and leaving, profile edit."""

import io
from datetime import timedelta

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import AgencyTeam, AgentProfile, VerificationStatus
from apps.agencies import services
from apps.agencies.models import AgencyInvitation
from apps.billing.models import Plan, Subscription
from apps.listings.models import ListingStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(make_user):
    return make_user(email="owner@example.com", is_agency=True, full_name="Olu Owner")


@pytest.fixture
def agency(owner):
    return AgencyTeam.objects.create(owner=owner, name="Sunrise Realty", city="Lagos", country="Nigeria",
                                     verification_status=VerificationStatus.VERIFIED)


@pytest.fixture
def starter(owner):
    """Agency Starter plan: 3 seats."""
    return Subscription.objects.create(user=owner, plan=Plan.objects.get(code="agency-starter"), status="active")


@pytest.fixture
def make_agent(make_user):
    def _make(email, verified=False, agency=None, full_name=None, **extra):
        user = make_user(email=email, is_agent=True, full_name=full_name or email.split("@")[0].title())
        AgentProfile.objects.create(
            user=user, agency=agency,
            verification_status=VerificationStatus.VERIFIED if verified else VerificationStatus.UNVERIFIED, **extra)
        return user
    return _make


# ---------------------------------------------------------------------------
# Directory and public pages
# ---------------------------------------------------------------------------
def test_directory_lists_verified_agents_first(client, make_agent, make_listing):
    plain = make_agent("aaron@example.com", full_name="Aaron Plain")
    make_listing(plain)
    make_listing(plain)
    make_agent("zed@example.com", verified=True, full_name="Zed Verified")
    html = client.get(reverse("agencies:agents")).content.decode()
    assert html.index("Zed Verified") < html.index("Aaron Plain")


def test_directory_filters(client, make_agent, make_listing, agency):
    a = make_agent("lagos@example.com", full_name="Lagos Agent", agency=agency, specialties="Luxury villas")
    make_listing(a, city="Lagos", country="Nigeria")
    b = make_agent("nbo@example.com", verified=True, full_name="Nairobi Agent")
    make_listing(b, city="Nairobi")
    url = reverse("agencies:agents")

    def names(**params):
        return {p.user.full_name for p in client.get(url, params).context["page"].object_list}

    assert names() == {"Lagos Agent", "Nairobi Agent"}
    assert names(city="Lagos") == {"Lagos Agent"}
    assert names(agency=agency.slug) == {"Lagos Agent"}
    assert names(verified="1") == {"Nairobi Agent"}
    assert names(q="villas") == {"Lagos Agent"}


def test_directory_hides_suspended_agents(client, make_agent):
    user = make_agent("gone@example.com", full_name="Gone Agent")
    user.is_suspended = True
    user.save()
    assert "Gone Agent" not in client.get(reverse("agencies:agents")).content.decode()
    assert client.get(reverse("agencies:agent", args=[user.pk])).status_code == 404


def test_agent_page_shows_published_listings_only(client, make_agent, make_listing):
    user = make_agent("show@example.com", verified=True)
    make_listing(user, title="Live flat")
    make_listing(user, title="Draft flat", status=ListingStatus.DRAFT)
    resp = client.get(reverse("agencies:agent", args=[user.pk]))
    html = resp.content.decode()
    assert resp.status_code == 200
    assert "Live flat" in html and "Draft flat" not in html
    assert "Verified" in html


def test_agent_page_404_for_non_agent(client, make_user):
    buyer = make_user(is_buyer=True)
    assert client.get(reverse("agencies:agent", args=[buyer.pk])).status_code == 404


def test_agency_page_and_list(client, agency, make_agent, make_listing):
    member = make_agent("m@example.com", agency=agency, full_name="Team Member")
    make_listing(member, agency=agency, title="Agency home")
    resp = client.get(reverse("agencies:agency", args=[agency.slug]))
    html = resp.content.decode()
    assert resp.status_code == 200
    assert "Team Member" in html and "Agency home" in html
    assert "Sunrise Realty" in client.get(reverse("agencies:agencies")).content.decode()


def test_agency_page_404_when_owner_suspended(client, agency, owner):
    owner.is_suspended = True
    owner.save()
    assert client.get(reverse("agencies:agency", args=[agency.slug])).status_code == 404


# ---------------------------------------------------------------------------
# Invitations and seats
# ---------------------------------------------------------------------------
def test_invite_sends_email_and_uses_a_seat(agency, owner, starter, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        inv = services.invite(agency, owner, "New.Agent@Example.com")
    assert inv.email == "new.agent@example.com"
    assert services.seats_used(agency) == 1
    assert len(mail.outbox) == 1
    assert inv.token in mail.outbox[0].body
    assert "Sunrise Realty" in mail.outbox[0].subject


def test_invite_needs_a_plan_with_seats(agency, owner):
    with pytest.raises(services.TeamError):
        services.invite(agency, owner, "a@example.com")


def test_invite_respects_seat_limit(agency, owner, starter, make_agent):
    make_agent("one@example.com", agency=agency)
    services.invite(agency, owner, "two@example.com")
    services.invite(agency, owner, "three@example.com")
    with pytest.raises(services.TeamError):
        services.invite(agency, owner, "four@example.com")


def test_invite_rejects_duplicates_members_and_self(agency, owner, starter, make_agent):
    make_agent("member@example.com", agency=agency)
    services.invite(agency, owner, "pending@example.com")
    for email in ("member@example.com", "PENDING@example.com", "owner@example.com"):
        with pytest.raises(services.TeamError):
            services.invite(agency, owner, email)


def test_expired_invitation_frees_the_seat_and_cannot_be_accepted(agency, owner, starter, make_agent):
    inv = services.invite(agency, owner, "late@example.com")
    AgencyInvitation.objects.filter(pk=inv.pk).update(expires_at=timezone.now() - timedelta(days=1))
    inv.refresh_from_db()
    assert services.seats_used(agency) == 0
    user = make_agent("late@example.com")
    with pytest.raises(services.TeamError):
        services.accept(inv, user)


def test_accept_moves_agent_and_listings_to_agency(agency, owner, starter, make_agent, make_listing):
    user = make_agent("joiner@example.com")
    listing = make_listing(user)
    inv = services.invite(agency, owner, "joiner@example.com")
    services.accept(inv, user)
    user.agent_profile.refresh_from_db()
    listing.refresh_from_db()
    inv.refresh_from_db()
    assert user.agent_profile.agency == agency
    assert listing.agency == agency
    assert inv.status == AgencyInvitation.Status.ACCEPTED


def test_accept_turns_a_buyer_into_an_agent(agency, owner, starter, make_user):
    user = make_user(email="buyer@example.com", is_buyer=True)
    inv = services.invite(agency, owner, "buyer@example.com")
    services.accept(inv, user)
    user.refresh_from_db()
    assert user.is_agent and user.agent_profile.agency == agency


def test_accept_rejects_wrong_email_and_other_agency(agency, owner, starter, make_agent, make_user):
    inv = services.invite(agency, owner, "right@example.com")
    with pytest.raises(services.TeamError):
        services.accept(inv, make_agent("wrong@example.com"))
    other_owner = make_user(email="other@example.com", is_agency=True)
    other = AgencyTeam.objects.create(owner=other_owner, name="Other Homes")
    busy = make_agent("busy@example.com", agency=other)
    inv2 = services.invite(agency, owner, "busy@example.com")
    with pytest.raises(services.TeamError):
        services.accept(inv2, busy)


def test_decline_and_revoke(agency, owner, starter, make_agent):
    inv = services.invite(agency, owner, "no@example.com")
    services.decline(inv, make_agent("no@example.com"))
    inv.refresh_from_db()
    assert inv.status == AgencyInvitation.Status.DECLINED
    inv2 = services.invite(agency, owner, "maybe@example.com")
    services.revoke(inv2, owner)
    inv2.refresh_from_db()
    assert inv2.status == AgencyInvitation.Status.REVOKED
    assert services.seats_used(agency) == 0


def test_remove_and_leave_keep_listings_with_the_agent(agency, owner, make_agent, make_listing):
    a = make_agent("a@example.com", agency=agency)
    b = make_agent("b@example.com", agency=agency)
    la, lb = make_listing(a, agency=agency), make_listing(b, agency=agency)
    services.detach(a, owner)
    services.detach(b, b)
    for listing in (la, lb):
        listing.refresh_from_db()
        assert listing.agency is None and listing.owner.agent_profile.agency is None


def test_detach_by_stranger_fails(agency, make_agent):
    a = make_agent("a@example.com", agency=agency)
    with pytest.raises(services.TeamError):
        services.detach(a, make_agent("stranger@example.com"))


# ---------------------------------------------------------------------------
# Views and permissions
# ---------------------------------------------------------------------------
def test_team_page_is_for_agency_owners_only(client, agency, owner, make_agent):
    client.force_login(make_agent("x@example.com"))
    assert client.get(reverse("agencies:team")).status_code == 403
    client.force_login(owner)
    assert client.get(reverse("agencies:team")).status_code == 200


def test_team_invite_view_and_flash(client, agency, owner, starter):
    client.force_login(owner)
    resp = client.post(reverse("agencies:team_invite"), {"email": "fresh@example.com"}, follow=True)
    assert AgencyInvitation.objects.filter(email="fresh@example.com").exists()
    assert "fresh@example.com" in resp.content.decode()
    client.post(reverse("agencies:team_invite"), {"email": "not-an-email"})
    assert AgencyInvitation.objects.count() == 1


def test_owner_cannot_remove_another_agencys_agent(client, owner, agency, make_user, make_agent):
    other = AgencyTeam.objects.create(owner=make_user(is_agency=True), name="Other")
    theirs = make_agent("theirs@example.com", agency=other)
    client.force_login(owner)
    resp = client.post(reverse("agencies:team_remove", args=[theirs.agent_profile.pk]))
    assert resp.status_code == 404
    theirs.agent_profile.refresh_from_db()
    assert theirs.agent_profile.agency == other


def test_invitation_page_accept_flow(client, agency, owner, starter, make_agent):
    inv = services.invite(agency, owner, "flow@example.com")
    url = reverse("agencies:invitation", args=[inv.token])
    assert "Sign in" in client.get(url).content.decode()
    user = make_agent("flow@example.com")
    client.force_login(user)
    resp = client.post(url, {"decision": "accept"})
    assert resp.status_code == 302
    user.agent_profile.refresh_from_db()
    assert user.agent_profile.agency == agency


def test_invitation_page_wrong_account(client, agency, owner, starter, make_agent):
    inv = services.invite(agency, owner, "flow@example.com")
    client.force_login(make_agent("someone@example.com"))
    resp = client.get(reverse("agencies:invitation", args=[inv.token]))
    assert resp.context["wrong_account"] is True


def test_agent_dashboard_shows_pending_invitations(client, agency, owner, starter, make_agent):
    user = make_agent("dash@example.com")
    services.invite(agency, owner, "dash@example.com")
    client.force_login(user)
    html = client.get(reverse("accounts:dashboard")).content.decode()
    assert "Sunrise Realty" in html and "Team invitations" in html


def test_leave_view(client, agency, make_agent):
    user = make_agent("leaver@example.com", agency=agency)
    client.force_login(user)
    client.post(reverse("agencies:team_leave"))
    user.agent_profile.refresh_from_db()
    assert user.agent_profile.agency is None


# ---------------------------------------------------------------------------
# Profile editing
# ---------------------------------------------------------------------------
def _jpeg_with_exif():
    img = Image.new("RGB", (40, 40), "red")
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # camera make
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return SimpleUploadedFile("me.jpg", buf.getvalue(), content_type="image/jpeg")


def test_profile_edit_saves_details_and_strips_photo_metadata(client, make_agent):
    user = make_agent("edit@example.com")
    client.force_login(user)
    resp = client.post(reverse("accounts:profile"), {
        "section": "profile", "full_name": "Edited Name", "phone": "+254 700 111 222",
        "city": "Mombasa", "country": "Kenya", "bio": "Hello", "avatar": _jpeg_with_exif(),
    })
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.full_name == "Edited Name"
    assert user.profile.city == "Mombasa"
    with Image.open(user.profile.avatar.path) as img:
        assert img.getexif().get(0x010F) is None


def test_profile_edit_agent_and_agency_sections(client, owner, agency, make_agent):
    user = make_agent("details@example.com")
    client.force_login(user)
    client.post(reverse("accounts:profile"), {"section": "agent", "license_number": "L-1", "specialties": "Rentals",
                                              "years_experience": "5"})
    user.agent_profile.refresh_from_db()
    assert user.agent_profile.specialties == "Rentals"
    client.force_login(owner)
    client.post(reverse("accounts:profile"), {"section": "agency", "name": "Sunrise Realty Group", "description": "",
                                              "city": "Abuja", "country": "Nigeria", "phone": "", "website": ""})
    agency.refresh_from_db()
    assert agency.name == "Sunrise Realty Group" and agency.city == "Abuja"
