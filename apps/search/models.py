from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites")
    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "listing"], name="unique_favorite")]

    def __str__(self):
        return f"{self.user} ♥ {self.listing_id}"


class SavedSearch(models.Model):
    """A search the user wants to come back to, optionally with a daily email digest."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_searches")
    name = models.CharField(_("name"), max_length=120)
    query = models.CharField(max_length=2000, help_text="URL query string of the search filters.")
    email_alerts = models.BooleanField(_("daily email"), default=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
