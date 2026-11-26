"""
Listing limits and lifecycle transitions.

Lifecycle (SPEC section 3):
    draft -> pending review -> published -> (expired | sold/rented | removed)

Owners move listings with `owner_transition`; staff moderation uses
`moderate` (approve / reject / request edits). Both raise TransitionError
with a user-facing message when a move is not allowed.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from .models import Listing, ListingLocation, ListingStatus, Purpose

# Listings that occupy a slot. Drafts are free to create and keep.
ACTIVE_STATUSES = (ListingStatus.PENDING, ListingStatus.PUBLISHED)
CLOSED_STATUSES = (ListingStatus.SOLD, ListingStatus.RENTED, ListingStatus.REMOVED, ListingStatus.EXPIRED)

FREE_SELLER_LISTINGS = 1
FREE_LANDLORD_LISTINGS = 2
LISTING_LIFETIME_DAYS = getattr(settings, "LISTING_LIFETIME_DAYS", 90)
MAX_PHOTOS = 20


class TransitionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Capacity:
    used: int
    free: int          # free allowance (individual owners)
    paid: int          # extra paid slots (milestone 6)
    plan: int          # subscription plan capacity (agents/agencies, milestone 6)
    needs_subscription: bool

    @property
    def total(self):
        return self.free + self.paid + self.plan

    @property
    def remaining(self):
        return max(0, self.total - self.used)

    @property
    def can_activate(self):
        # Agents and agencies need a plan; extra slots add to a plan, they don't replace it.
        return not self.needs_subscription and self.remaining > 0


def free_allowance(user):
    allowance = 0
    if user.is_seller:
        allowance += FREE_SELLER_LISTINGS
    if user.is_landlord:
        allowance += FREE_LANDLORD_LISTINGS
    return allowance


def paid_extra_slots(user):
    """Extra listing slots bought with one-time payments (each lasts EXTRA_LISTING_DAYS)."""
    from apps.billing.services import paid_extra_slots as slots

    return slots(user)


def plan_capacity(user):
    """Active listings allowed by the user's (or their agency's) subscription plan."""
    from apps.billing.services import plan_scope

    plan, _scope = plan_scope(user)
    return plan.listing_limit if plan else 0


def active_count(user):
    """Active listings counted against this user's allowance.

    With an agency plan, every listing in the agency counts towards the shared limit.
    """
    from apps.billing.services import plan_scope

    plan, scope = plan_scope(user)
    if plan and (user.is_agent or user.is_agency):
        return scope.filter(status__in=ACTIVE_STATUSES).count()
    return Listing.objects.filter(owner=user, status__in=ACTIVE_STATUSES).count()


def capacity_for(user):
    professional = user.is_agent or user.is_agency
    plan = plan_capacity(user) if professional else 0
    return Capacity(
        used=active_count(user),
        free=free_allowance(user),
        paid=paid_extra_slots(user),
        plan=plan,
        needs_subscription=professional and plan == 0 and free_allowance(user) == 0,
    )


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------
def missing_for_review(listing):
    """What still has to be added before a listing can be submitted."""
    missing = []
    if not listing.photos.exists():
        missing.append(_("at least one photo"))
    if not ListingLocation.objects.filter(listing=listing).exists():
        missing.append(_("a map pin"))
    if not listing.description.strip():
        missing.append(_("a description"))
    return missing


# ---------------------------------------------------------------------------
# Owner transitions
# ---------------------------------------------------------------------------
OWNER_ACTIONS = {
    # action: (allowed from, to, label)
    "submit": ((ListingStatus.DRAFT, ListingStatus.EXPIRED), ListingStatus.PENDING, gettext_lazy("Submit for review")),
    "withdraw": ((ListingStatus.PENDING,), ListingStatus.DRAFT, gettext_lazy("Withdraw to draft")),
    "mark_sold": ((ListingStatus.PUBLISHED,), ListingStatus.SOLD, gettext_lazy("Mark as sold")),
    "mark_rented": ((ListingStatus.PUBLISHED,), ListingStatus.RENTED, gettext_lazy("Mark as rented")),
    "remove": (
        (ListingStatus.DRAFT, ListingStatus.PENDING, ListingStatus.PUBLISHED, ListingStatus.EXPIRED),
        ListingStatus.REMOVED,
        gettext_lazy("Remove listing"),
    ),
}


def available_owner_actions(listing):
    actions = []
    for name, (sources, _target, label) in OWNER_ACTIONS.items():
        if listing.status not in sources:
            continue
        if name == "mark_sold" and listing.purpose != Purpose.SALE:
            continue
        if name == "mark_rented" and listing.purpose != Purpose.RENT:
            continue
        actions.append((name, label))
    return actions


@transaction.atomic
def owner_transition(listing, user, action):
    if action not in OWNER_ACTIONS:
        raise TransitionError(_("Unknown action."))
    if listing.owner_id != user.pk:
        raise TransitionError(_("Only the owner can change this listing."))
    # Lock the owner's listings so two submissions cannot both take the last slot.
    list(Listing.objects.select_for_update().filter(owner=user).values_list("pk", flat=True))
    listing.refresh_from_db()
    if action not in dict(available_owner_actions(listing)):
        raise TransitionError(_("That action is not available for a listing that is %(status)s.")
                              % {"status": listing.get_status_display().lower()})
    target = OWNER_ACTIONS[action][1]
    if target == ListingStatus.PENDING:
        missing = missing_for_review(listing)
        if missing:
            raise TransitionError(_("Add %(items)s before submitting.") % {"items": ", ".join(str(m) for m in missing)})
        cap = capacity_for(user)
        if not cap.can_activate:
            if cap.needs_subscription:
                raise TransitionError(_("Agents and agencies need an active subscription to publish listings."))
            raise TransitionError(_("You have used all %(n)s of your active listing slots. Close a listing, buy an extra slot or upgrade your plan.")
                                  % {"n": cap.total})
        listing.moderation_note = ""
    listing.status = target
    listing.save(update_fields=["status", "moderation_note", "updated_at"])
    return listing


def mark_edited(listing):
    """Content edits to a live listing send it back to review (see QUESTIONS.md Q11)."""
    if listing.status == ListingStatus.PUBLISHED:
        listing.status = ListingStatus.PENDING
        return True
    return False


# ---------------------------------------------------------------------------
# Staff moderation
# ---------------------------------------------------------------------------
@transaction.atomic
def moderate(listing, staff_user, decision, note=""):
    """decision: 'approve' | 'reject' | 'request_edits'."""
    if not (staff_user and staff_user.is_staff):
        raise TransitionError(_("Only staff can moderate listings."))
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if listing.status != ListingStatus.PENDING:
        raise TransitionError(_("Only listings pending review can be moderated."))
    now = timezone.now()
    if decision == "approve":
        listing.status = ListingStatus.PUBLISHED
        listing.published_at = now
        listing.expires_at = now + timedelta(days=LISTING_LIFETIME_DAYS)
        listing.moderation_note = ""
    elif decision in ("reject", "request_edits"):
        if not note.strip():
            raise TransitionError(_("Give the owner a reason."))
        listing.status = ListingStatus.DRAFT
        listing.moderation_note = note.strip()
    else:
        raise TransitionError(_("Unknown decision."))
    listing.save(update_fields=["status", "published_at", "expires_at", "moderation_note", "updated_at"])
    return listing


def expire_due_listings(now=None):
    now = now or timezone.now()
    return Listing.objects.filter(status=ListingStatus.PUBLISHED, expires_at__lte=now).update(
        status=ListingStatus.EXPIRED, updated_at=now
    )
