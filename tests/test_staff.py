"""Admin dashboard: access, overview, moderation, listings table, users, verifications."""

import pytest
from django.conf import settings
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import AgentProfile, VerificationDocument, VerificationStatus
from apps.listings.models import Listing, ListingPhoto, ListingStatus
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db
S = ListingStatus
PDF = b"%PDF-1.4\n%%EOF"

STAFF_PAGES = ["staff:overview", "staff:moderation", "staff:listings", "staff:users", "staff:verifications"]


@pytest.fixture
def staff(client, make_user):
    user = make_user(is_staff=True, full_name="Sam Staff")
    client.force_login(user)
    return user


@pytest.fixture
def owner(make_user):
    return make_user(email="owner@example.com", full_name="Olu Owner", is_seller=True)


def with_photo(listing):
    ListingPhoto.objects.create(listing=listing, image="seed/x.jpg")
    return listing


# --- access ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", STAFF_PAGES)
def test_staff_pages_require_staff(client, make_user, name):
    response = client.get(reverse(name))
    assert response.status_code == 302 and reverse("accounts:staff_login") in response.url
    client.force_login(make_user(is_agent=True))
    assert client.get(reverse(name)).status_code == 403


@pytest.mark.parametrize("name", STAFF_PAGES)
def test_staff_pages_render(client, staff, name):
    assert client.get(reverse(name)).status_code == 200


def test_staff_actions_require_post_and_staff(client, make_user, owner, make_listing):
    listing = make_listing(owner, status=S.PENDING)
    client.force_login(make_user(is_agent=True))
    assert client.post(reverse("staff:moderation_action", args=[listing.pk]), {"decision": "approve"}).status_code == 403
    listing.refresh_from_db()
    assert listing.status == S.PENDING


# --- overview -------------------------------------------------------------------------
def test_overview_metrics(client, staff, owner, make_listing, make_user):
    make_listing(owner, status=S.PUBLISHED)
    make_listing(owner, status=S.PENDING)
    make_listing(owner, status=S.REMOVED)
    make_user(is_agent=True)
    ctx = client.get(reverse("staff:overview")).context
    m = ctx["metrics"]
    assert (m["listings_total"], m["published"], m["pending"]) == (2, 1, 1)
    roles = dict((r.value, n) for r, n in ctx["roles"])
    assert roles["seller"] == 1 and roles["agent"] == 1
    assert len(ctx["listing_series"]) == 30 and ctx["listing_series"][-1]["count"] == 3
    assert any(a["kind"] == "review" for a in ctx["activity"])


# --- moderation transitions through the dashboard -------------------------------------------
def test_approve_publishes_and_emails_owner(client, staff, owner, make_listing, django_capture_on_commit_callbacks):
    listing = with_photo(make_listing(owner, status=S.PENDING, title="Garden house"))
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("staff:moderation_action", args=[listing.pk]), {"decision": "approve"})
    listing.refresh_from_db()
    assert listing.status == S.PUBLISHED and listing.published_at and listing.expires_at
    assert mail.outbox[-1].to == ["owner@example.com"] and "live" in mail.outbox[-1].subject


@pytest.mark.parametrize("decision, subject", [("reject", "not approved"), ("request_edits", "Changes requested")])
def test_reject_and_request_edits(client, staff, owner, make_listing, django_capture_on_commit_callbacks, decision, subject):
    listing = make_listing(owner, status=S.PENDING)
    client.post(reverse("staff:moderation_action", args=[listing.pk]), {"decision": decision, "note": ""})
    listing.refresh_from_db()
    assert listing.status == S.PENDING  # a reason is required
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("staff:moderation_action", args=[listing.pk]), {"decision": decision, "note": "Photos are too dark."})
    listing.refresh_from_db()
    assert listing.status == S.DRAFT and listing.moderation_note == "Photos are too dark."
    assert subject in mail.outbox[-1].subject and "Photos are too dark." in mail.outbox[-1].body


def test_queue_lists_only_pending_oldest_first(client, staff, owner, make_listing):
    first = make_listing(owner, status=S.PENDING, title="First")
    make_listing(owner, status=S.PENDING, title="Second")
    make_listing(owner, status=S.DRAFT, title="Draft")
    Listing.objects.filter(pk=first.pk).update(updated_at=first.updated_at.replace(year=2020))
    titles = [l.title for l in client.get(reverse("staff:moderation")).context["queue"]]
    assert titles == ["First", "Second"]


def test_bulk_approve(client, staff, owner, make_listing):
    a, b = make_listing(owner, status=S.PENDING), make_listing(owner, status=S.PENDING)
    draft = make_listing(owner, status=S.DRAFT)
    client.post(reverse("staff:moderation_bulk"), {"ids": [a.pk, b.pk, draft.pk]})
    assert set(Listing.objects.filter(status=S.PUBLISHED).values_list("pk", flat=True)) == {a.pk, b.pk}


# --- listings table ---------------------------------------------------------------------
def test_listings_filters_and_sorting(client, staff, owner, make_listing):
    make_listing(owner, title="Cheap Accra", city="Accra", country="Ghana", price=100)
    make_listing(owner, title="Dear Accra", city="Accra", country="Ghana", price=900)
    make_listing(owner, title="Lagos draft", city="Lagos", country="Nigeria", status=S.DRAFT)
    url = reverse("staff:listings")
    titles = lambda r: [l.title for l in r.context["table"].page.object_list]
    assert titles(client.get(url, {"country": "Ghana", "sort": "price", "dir": "desc"})) == ["Dear Accra", "Cheap Accra"]
    assert titles(client.get(url, {"status": "draft"})) == ["Lagos draft"]
    assert len(titles(client.get(url, {"q": "olu owner"}))) == 3  # search by owner name
    partial = client.get(url, {"q": "accra"}, HTTP_HX_REQUEST="true")
    assert [t.name for t in partial.templates][0] == "staff/_listings_table.html"
    assert client.get(url, {"sort": "nonsense"}).status_code == 200


def test_bulk_feature_unpublish_and_delete(client, staff, owner, make_listing):
    live = make_listing(owner, status=S.PUBLISHED)
    draft = make_listing(owner, status=S.DRAFT)
    bulk = reverse("staff:listings_bulk")
    client.post(bulk, {"action": "feature", "ids": [live.pk, draft.pk]})
    assert set(Listing.objects.filter(is_featured=True).values_list("pk", flat=True)) == {live.pk}  # only published
    client.post(bulk, {"action": "unpublish", "ids": [live.pk]})
    live.refresh_from_db()
    assert live.status == S.DRAFT and not live.is_featured and "Unpublished" in live.moderation_note
    client.post(bulk, {"action": "delete", "ids": [draft.pk]})  # no confirmation text
    assert Listing.objects.filter(pk=draft.pk).exists()
    client.post(bulk, {"action": "delete", "ids": [draft.pk], "confirm": "DELETE"})
    assert not Listing.objects.filter(pk=draft.pk).exists()


# --- users ---------------------------------------------------------------------------------
def test_users_search_and_role_filter(client, staff, make_user):
    make_user(full_name="Ngozi Agent", email="ngozi@example.com", is_agent=True)
    make_user(full_name="Ben Buyer", is_buyer=True)
    r = client.get(reverse("staff:users"), {"role": "agent"})
    assert [u.full_name for u in r.context["table"].page.object_list] == ["Ngozi Agent"]
    r = client.get(reverse("staff:users"), {"q": "ngozi@"})
    assert [u.email for u in r.context["table"].page.object_list] == ["ngozi@example.com"]


def test_suspend_signs_user_out_and_blocks_login(client, staff, make_user):
    member = make_user(email="m@example.com", is_buyer=True)
    other = client.__class__()
    other.force_login(member)
    client.post(reverse("staff:user_action", args=[member.pk, "suspend"]))
    member.refresh_from_db()
    assert member.is_suspended
    assert other.get(reverse("accounts:dashboard")).url.startswith(reverse("accounts:login"))  # signed out on next request
    assert not other.login(username="m@example.com", password=PASSWORD)
    client.post(reverse("staff:user_action", args=[member.pk, "unsuspend"]))
    member.refresh_from_db()
    assert not member.is_suspended


def test_change_roles(client, staff, make_user):
    member = make_user(is_buyer=True)
    client.post(reverse("staff:user_action", args=[member.pk, "roles"]), {"roles": ["landlord", "agent"]})
    member.refresh_from_db()
    assert member.is_landlord and member.is_agent and not member.is_buyer and not member.is_staff
    assert AgentProfile.objects.filter(user=member).exists()
    client.post(reverse("staff:user_action", args=[member.pk, "roles"]), {"roles": []})  # must keep one
    member.refresh_from_db()
    assert member.is_landlord


def test_staff_cannot_suspend_or_edit_themselves(client, staff):
    client.post(reverse("staff:user_action", args=[staff.pk, "suspend"]))
    staff.refresh_from_db()
    assert not staff.is_suspended


# --- verifications -------------------------------------------------------------------------
@pytest.fixture
def agent(client, make_user):
    user = make_user(email="agent@example.com", full_name="Ade Agent", is_agent=True)
    AgentProfile.objects.create(user=user)
    return user


def upload(client, user, content=PDF, name="license.pdf"):
    client.force_login(user)
    return client.post(reverse("accounts:verification_upload"), {"document": SimpleUploadedFile(name, content)})


def test_agent_uploads_license_privately(client, agent):
    upload(client, agent)
    doc = VerificationDocument.objects.get()
    agent.agent_profile.refresh_from_db()
    assert doc.status == "pending" and agent.agent_profile.verification_status == VerificationStatus.PENDING
    assert doc.document.path.startswith(str(settings.PRIVATE_MEDIA_ROOT))
    assert not doc.document.path.startswith(str(settings.MEDIA_ROOT) + "\\verification")


@pytest.mark.parametrize("content, name", [(b"<html>evil</html>", "license.pdf"), (PDF, "license.exe"), (b"MZ...", "license.png")])
def test_upload_rejects_wrong_files(client, agent, content, name):
    upload(client, agent, content, name)
    assert not VerificationDocument.objects.exists()


def test_buyers_cannot_upload(client, make_user):
    response = upload(client, make_user(is_buyer=True))
    assert response.status_code == 403


def test_review_approve_and_reject(client, agent, make_user, django_capture_on_commit_callbacks):
    upload(client, agent)
    doc = VerificationDocument.objects.get()
    staff_user = make_user(is_staff=True)
    client.force_login(staff_user)
    file_response = client.get(reverse("staff:verification_file", args=[doc.pk]))
    assert file_response.status_code == 200 and file_response["Content-Security-Policy"] == "sandbox"
    client.post(reverse("staff:verification_review", args=[doc.pk]), {"decision": "reject", "reason": ""})
    doc.refresh_from_db()
    assert doc.status == "pending"  # reason required
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("staff:verification_review", args=[doc.pk]), {"decision": "approve"})
    doc.refresh_from_db()
    agent.agent_profile.refresh_from_db()
    assert doc.status == "approved" and doc.reviewed_by == staff_user
    assert agent.agent_profile.verification_status == VerificationStatus.VERIFIED
    assert mail.outbox[-1].to == ["agent@example.com"] and "verified" in mail.outbox[-1].subject


def test_license_file_is_staff_only(client, agent, make_user):
    upload(client, agent)
    doc = VerificationDocument.objects.get()
    assert client.get(reverse("staff:verification_file", args=[doc.pk])).status_code == 403  # the agent themself
    client.logout()
    assert client.get(reverse("staff:verification_file", args=[doc.pk])).status_code == 302
