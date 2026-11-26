"""Billing data (SPEC sections 8 and 9): plans, subscriptions, one-time purchases, featured placements.

No property sale or rental payments: only platform services are billed.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Plan(models.Model):
    class Audience(models.TextChoices):
        AGENT = "agent", _("Agent")
        AGENCY = "agency", _("Agency")

    code = models.SlugField(unique=True)
    name = models.CharField(_("name"), max_length=80)
    audience = models.CharField(max_length=10, choices=Audience.choices)
    price_monthly = models.DecimalField(_("monthly price"), max_digits=10, decimal_places=2)
    listing_limit = models.PositiveIntegerField(_("active listings"))
    seats = models.PositiveIntegerField(_("agent seats"), default=1)
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["audience", "sort_order", "price_monthly"]

    def __str__(self):
        return self.name


class Subscription(models.Model):
    class Status(models.TextChoices):
        INCOMPLETE = "incomplete", _("Incomplete")
        INCOMPLETE_EXPIRED = "incomplete_expired", _("Expired before payment")
        TRIALING = "trialing", _("Trial")
        ACTIVE = "active", _("Active")
        PAST_DUE = "past_due", _("Payment overdue")
        UNPAID = "unpaid", _("Unpaid")
        CANCELED = "canceled", _("Canceled")
        PAUSED = "paused", _("Paused")

    # Statuses that keep listing capacity. Past due keeps access while the provider retries the card.
    GRANTS_ACCESS = (Status.ACTIVE, Status.TRIALING, Status.PAST_DUE)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INCOMPLETE)
    provider = models.CharField(max_length=20, default="stripe")
    provider_subscription_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    provider_customer_id = models.CharField(max_length=100, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} · {self.plan} ({self.status})"

    @property
    def grants_access(self):
        return self.status in self.GRANTS_ACCESS


class Purchase(models.Model):
    class Kind(models.TextChoices):
        EXTRA_LISTING = "extra_listing", _("Extra listing slot")
        FEATURED = "featured", _("Featured placement")
        SUBSCRIPTION = "subscription", _("Subscription payment")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PAID = "paid", _("Paid")
        FAILED = "failed", _("Failed")
        REFUNDED = "refunded", _("Refunded")
        CANCELED = "canceled", _("Canceled")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="purchases")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    listing = models.ForeignKey("listings.Listing", on_delete=models.SET_NULL, null=True, blank=True, related_name="purchases")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=20, default="stripe")
    checkout_session_id = models.CharField(max_length=200, unique=True, null=True, blank=True)
    payment_intent_id = models.CharField(max_length=100, blank=True, db_index=True)
    invoice_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="End of the benefit (extra listing slots).")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.amount} {self.currency} ({self.status})"


class FeaturedPlacementQuerySet(models.QuerySet):
    def active(self, now=None):
        now = now or timezone.now()
        return self.filter(starts_at__lte=now, ends_at__gt=now)


class FeaturedPlacement(models.Model):
    """A paid, time-limited featured slot for one listing."""

    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="featured_placements")
    purchase = models.OneToOneField(Purchase, on_delete=models.SET_NULL, null=True, blank=True, related_name="placement")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(db_index=True)
    ended_processed = models.BooleanField(default=False)

    objects = FeaturedPlacementQuerySet.as_manager()

    class Meta:
        ordering = ["-ends_at"]

    def __str__(self):
        return f"Featured {self.listing_id} until {self.ends_at:%Y-%m-%d}"


class WebhookEvent(models.Model):
    """Provider events already processed, so retries are not applied twice."""

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=100, unique=True)
    type = models.CharField(max_length=100)
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider} {self.type} {self.event_id}"
