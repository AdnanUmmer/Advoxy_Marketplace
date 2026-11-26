import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

INVITE_DAYS = 14


def new_token():
    return secrets.token_urlsafe(24)


def default_expiry():
    return timezone.now() + timedelta(days=INVITE_DAYS)


class AgencyInvitation(models.Model):
    """An agency owner's invitation for an agent to join the team (uses one seat while pending)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")
        REVOKED = "revoked", _("Revoked")

    agency = models.ForeignKey("accounts.AgencyTeam", on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField(_("agent's email"))
    token = models.CharField(max_length=64, unique=True, default=new_token)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=default_expiry)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} → {self.agency} ({self.status})"

    @property
    def is_open(self):
        return self.status == self.Status.PENDING and self.expires_at > timezone.now()
