"""Agency teams: seats, invitations, joining, leaving and removal."""

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import AgentProfile
from apps.core.emails import send_templated_email
from apps.listings.models import Listing

from .models import AgencyInvitation


class TeamError(Exception):
    pass


def seat_limit(agency):
    """Agent seats from the agency owner's active plan (0 without a plan)."""
    from apps.billing.services import active_subscription

    sub = active_subscription(agency.owner)
    return sub.plan.seats if sub else 0


def open_invitations(agency):
    return agency.invitations.filter(status=AgencyInvitation.Status.PENDING, expires_at__gt=timezone.now())


def seats_used(agency):
    return agency.agents.count() + open_invitations(agency).count()


@transaction.atomic
def invite(agency, inviter, email):
    email = email.strip().lower()
    if inviter.pk != agency.owner_id:
        raise TeamError(_("Only the agency owner can invite agents."))
    if seats_used(agency) >= seat_limit(agency):
        raise TeamError(_("All your plan's agent seats are in use. Remove an agent, revoke an invitation or upgrade your plan."))
    if agency.agents.filter(user__email__iexact=email).exists():
        raise TeamError(_("That agent is already on your team."))
    if open_invitations(agency).filter(email__iexact=email).exists():
        raise TeamError(_("You've already invited that email address."))
    if email == agency.owner.email.lower():
        raise TeamError(_("You can't invite yourself."))
    inv = AgencyInvitation.objects.create(agency=agency, email=email, invited_by=inviter)
    transaction.on_commit(lambda: send_templated_email("agency_invitation", email, {
        "agency_name": agency.name, "inviter_name": inviter.full_name,
        "path": reverse("agencies:invitation", args=[inv.token]),
    }))
    return inv


def revoke(invitation, user):
    if user.pk != invitation.agency.owner_id:
        raise TeamError(_("Only the agency owner can revoke invitations."))
    if invitation.status == AgencyInvitation.Status.PENDING:
        invitation.status = AgencyInvitation.Status.REVOKED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at"])


@transaction.atomic
def accept(invitation, user):
    if not invitation.is_open:
        raise TeamError(_("This invitation is no longer valid."))
    if user.email.lower() != invitation.email.lower():
        raise TeamError(_("This invitation was sent to a different email address."))
    if user.is_agency:
        raise TeamError(_("Agency accounts can't join another agency."))
    profile, _created = AgentProfile.objects.get_or_create(user=user)
    if profile.agency_id and profile.agency_id != invitation.agency_id:
        raise TeamError(_("Leave your current agency before joining another."))
    if not user.is_agent:
        user.is_agent = True
        user.save(update_fields=["is_agent"])
    profile.agency = invitation.agency
    profile.save(update_fields=["agency"])
    # The agent's existing listings move under the agency's plan.
    Listing.objects.filter(owner=user).update(agency=invitation.agency)
    invitation.status = AgencyInvitation.Status.ACCEPTED
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at"])
    return profile


def decline(invitation, user):
    if user.email.lower() != invitation.email.lower():
        raise TeamError(_("This invitation was sent to a different email address."))
    if invitation.status == AgencyInvitation.Status.PENDING:
        invitation.status = AgencyInvitation.Status.DECLINED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at"])


@transaction.atomic
def detach(agent_user, by_user):
    """Remove an agent from their agency (by the owner) or leave it (by the agent)."""
    profile = AgentProfile.objects.select_related("agency").filter(user=agent_user).first()
    if not profile or not profile.agency_id:
        raise TeamError(_("This agent isn't on a team."))
    agency = profile.agency
    if by_user.pk not in (agent_user.pk, agency.owner_id):
        raise TeamError(_("You can't change this team."))
    profile.agency = None
    profile.save(update_fields=["agency"])
    Listing.objects.filter(owner=agent_user, agency=agency).update(agency=None)
    return agency


def invitations_for(user):
    if not user.is_authenticated:
        return AgencyInvitation.objects.none()
    return AgencyInvitation.objects.filter(email__iexact=user.email, status=AgencyInvitation.Status.PENDING,
                                           expires_at__gt=timezone.now()).select_related("agency")


