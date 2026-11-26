from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Setting(models.Model):
    """Admin-editable configuration (SPEC section 9). Keys and defaults live in apps/core/site_settings.py."""

    key = models.CharField(max_length=60, primary_key=True)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    def __str__(self):
        return self.key


class AuditLog(models.Model):
    """Who changed what and when. Written by apps/core/audit.py; never edited."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="audit_entries")
    actor_label = models.CharField(max_length=254, blank=True)  # kept if the actor is deleted
    action = models.CharField(_("action"), max_length=60, db_index=True)
    target_type = models.CharField(max_length=40, blank=True, db_index=True)
    target_id = models.CharField(max_length=40, blank=True)
    target_label = models.CharField(max_length=200, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_label} {self.action} {self.target_label}"
