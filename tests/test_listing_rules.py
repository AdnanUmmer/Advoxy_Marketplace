"""Listing limits, owner lifecycle transitions and staff moderation transitions."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core import site_settings
from apps.listings import rules
from apps.listings.models import ListingPhoto, ListingStatus

pytestmark = pytest.mark.django_db
S = ListingStatus


@pytest.fixture
def ready_listing(make_listing):
    """A draft with a photo and a pin, ready to submit."""

    def _make(owner, **kw):
        listing = make_listing(owner, status=kw.pop("status", S.DRAFT), **kw)
        photo = ListingPhoto(listing=listing, position=0)
        photo.image.name = "seed/test.jpg"
        photo.save()
        return listing

    return _make


# --- limits -----------------------------------------------------------------
@pytest.mark.parametrize("flags, allowance", [
    ({"is_seller": True}, 1),
    ({"is_landlord": True}, 2),
    ({"is_seller": True, "is_landlord": True}, 3),
    ({"is_buyer": True}, 0),
])
def test_free_allowance_by_role(make_user, flags, allowance):
    assert rules.capacity_for(make_user(**flags)).total == allowance


def test_drafts_do_not_count_but_pending_and_published_do(make_user, make_listing):
    owner = make_user(is_landlord=True)
    make_listing(owner, status=S.DRAFT)
    assert rules.capacity_for(owner).used == 0
    make_listing(owner, status=S.PENDING)
    make_listing(owner, status=S.PUBLISHED)
    cap = rules.capacity_for(owner)
    assert cap.used == 2 and cap.remaining == 0 and not cap.can_activate


def test_seller_cannot_submit_second_listing(make_user, ready_listing):
    seller = make_user(is_seller=True)
    first, second = ready_listing(seller), ready_listing(seller)
    rules.owner_transition(first, seller, "submit")
    with pytest.raises(rules.TransitionError, match="active listing slots"):
        rules.owner_transition(second, seller, "submit")
    second.refresh_from_db()
    assert second.status == S.DRAFT


def test_landlord_gets_two_slots(make_user, ready_listing):
    landlord = make_user(is_landlord=True)
    a, b, c = (ready_listing(landlord, purpose="rent") for _ in range(3))
    rules.owner_transition(a, landlord, "submit")
    rules.owner_transition(b, landlord, "submit")
    with pytest.raises(rules.TransitionError):
        rules.owner_transition(c, landlord, "submit")


def test_closing_a_listing_frees_a_slot(make_user, ready_listing):
    seller = make_user(is_seller=True)
    live = ready_listing(seller, status=S.PUBLISHED)
    draft = ready_listing(seller)
    with pytest.raises(rules.TransitionError):
        rules.owner_transition(draft, seller, "submit")
    rules.owner_transition(live, seller, "mark_sold")
    rules.owner_transition(draft, seller, "submit")
    draft.refresh_from_db()
    assert draft.status == S.PENDING


def test_agents_need_a_subscription(make_user, ready_listing):
    agent = make_user(is_agent=True)
    assert rules.capacity_for(agent).needs_subscription
    with pytest.raises(rules.TransitionError, match="subscription"):
        rules.owner_transition(ready_listing(agent), agent, "submit")


def test_submit_requires_photo_and_pin(make_user, make_listing):
    seller = make_user(is_seller=True)
    bare = make_listing(seller, status=S.DRAFT)
    bare.location.delete()
    bare.refresh_from_db()
    with pytest.raises(rules.TransitionError, match="photo"):
        rules.owner_transition(bare, seller, "submit")
    assert {str(m) for m in rules.missing_for_review(bare)} == {"at least one photo", "a map pin"}


# --- owner transitions --------------------------------------------------------
def test_only_owner_can_transition(make_user, ready_listing):
    owner, other = make_user(is_seller=True), make_user(is_seller=True)
    listing = ready_listing(owner)
    with pytest.raises(rules.TransitionError, match="owner"):
        rules.owner_transition(listing, other, "submit")


def test_available_actions_follow_status_and_purpose(make_user, ready_listing):
    owner = make_user(is_seller=True, is_landlord=True)
    sale = ready_listing(owner, status=S.PUBLISHED, purpose="sale")
    rent = ready_listing(owner, status=S.PUBLISHED, purpose="rent")
    assert dict(rules.available_owner_actions(sale)).keys() == {"mark_sold", "remove"}
    assert dict(rules.available_owner_actions(rent)).keys() == {"mark_rented", "remove"}
    assert dict(rules.available_owner_actions(ready_listing(owner))).keys() == {"submit", "remove"}
    with pytest.raises(rules.TransitionError):
        rules.owner_transition(sale, owner, "mark_rented")


def test_withdraw_and_remove(make_user, ready_listing):
    owner = make_user(is_seller=True)
    listing = ready_listing(owner)
    rules.owner_transition(listing, owner, "submit")
    rules.owner_transition(listing, owner, "withdraw")
    assert listing.status == S.DRAFT
    rules.owner_transition(listing, owner, "remove")
    assert listing.status == S.REMOVED
    with pytest.raises(rules.TransitionError):
        rules.owner_transition(listing, owner, "submit")


def test_expired_listing_can_be_resubmitted(make_user, ready_listing):
    owner = make_user(is_seller=True)
    listing = ready_listing(owner, status=S.EXPIRED)
    rules.owner_transition(listing, owner, "submit")
    assert listing.status == S.PENDING


def test_editing_live_listing_sends_it_back_to_review(make_user, ready_listing):
    listing = ready_listing(make_user(is_seller=True), status=S.PUBLISHED)
    assert rules.mark_edited(listing) and listing.status == S.PENDING
    draft = ready_listing(make_user(is_seller=True))
    assert not rules.mark_edited(draft) and draft.status == S.DRAFT


# --- staff moderation ----------------------------------------------------------
def test_approve_publishes_with_expiry(make_user, ready_listing):
    staff = make_user(is_staff=True)
    listing = ready_listing(make_user(is_seller=True), status=S.PENDING)
    listing = rules.moderate(listing, staff, "approve")
    assert listing.status == S.PUBLISHED
    assert listing.published_at and listing.expires_at - listing.published_at == timedelta(days=site_settings.get("listing_lifetime_days"))


@pytest.mark.parametrize("decision", ["reject", "request_edits"])
def test_reject_or_request_edits_needs_reason_and_returns_to_draft(make_user, ready_listing, decision):
    staff = make_user(is_staff=True)
    listing = ready_listing(make_user(is_seller=True), status=S.PENDING)
    with pytest.raises(rules.TransitionError, match="reason"):
        rules.moderate(listing, staff, decision, note="  ")
    listing = rules.moderate(listing, staff, decision, note="Photos are blurry.")
    assert listing.status == S.DRAFT and listing.moderation_note == "Photos are blurry."


def test_moderation_only_on_pending_and_only_by_staff(make_user, ready_listing):
    staff = make_user(is_staff=True)
    draft = ready_listing(make_user(is_seller=True))
    with pytest.raises(rules.TransitionError, match="pending"):
        rules.moderate(draft, staff, "approve")
    pending = ready_listing(make_user(is_seller=True), status=S.PENDING)
    with pytest.raises(rules.TransitionError, match="staff"):
        rules.moderate(pending, make_user(is_agent=True), "approve")


def test_resubmitting_clears_moderation_note(make_user, ready_listing):
    owner = make_user(is_seller=True)
    listing = ready_listing(owner, status=S.PENDING)
    rules.moderate(listing, make_user(is_staff=True), "request_edits", note="Add the floor area.")
    listing.refresh_from_db()
    rules.owner_transition(listing, owner, "submit")
    assert listing.moderation_note == ""


def test_expire_due_listings(make_user, ready_listing):
    owner = make_user(is_landlord=True)
    old = ready_listing(owner, status=S.PUBLISHED)
    old.expires_at = timezone.now() - timedelta(minutes=1)
    old.save()
    fresh = ready_listing(owner, status=S.PUBLISHED)
    fresh.expires_at = timezone.now() + timedelta(days=5)
    fresh.save()
    assert rules.expire_due_listings() == 1
    old.refresh_from_db(); fresh.refresh_from_db()
    assert old.status == S.EXPIRED and fresh.status == S.PUBLISHED
