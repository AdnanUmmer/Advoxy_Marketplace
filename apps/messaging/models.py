from django.conf import settings
from django.db import models
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class Inquiry(models.Model):
    """The contact form submission from a listing page. Starts (or continues) a thread."""

    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="inquiries")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="inquiries_sent")
    thread = models.ForeignKey("Thread", on_delete=models.CASCADE, related_name="inquiries")
    name = models.CharField(_("name"), max_length=150)
    email = models.EmailField(_("email"))
    phone = models.CharField(_("phone"), max_length=32, blank=True)
    message = models.TextField(_("message"), max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = _("inquiries")

    def __str__(self):
        return f"Inquiry from {self.name} on {self.listing_id}"


class ThreadQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(Q(buyer=user) | Q(owner=user))

    def with_unread(self, user):
        """Annotate `unread` = messages from the other person after the user's last read."""
        last_read = MessageRead.objects.filter(thread=OuterRef("pk"), user=user).values("last_read_at")[:1]
        return self.annotate(user_last_read=Subquery(last_read)).annotate(
            unread=Count(
                "messages",
                filter=~Q(messages__sender=user)
                & (Q(user_last_read__isnull=True) | Q(messages__created_at__gt=F("user_last_read"))),
            )
        )


class Thread(models.Model):
    """One conversation per (listing, interested user). The owner is the listing owner."""

    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="threads")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="threads_started")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="threads_received")
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(db_index=True)

    objects = ThreadQuerySet.as_manager()

    class Meta:
        ordering = ["-last_message_at"]
        constraints = [models.UniqueConstraint(fields=["listing", "buyer"], name="one_thread_per_listing_buyer")]

    def __str__(self):
        return f"Thread {self.pk} on {self.listing_id}"

    def get_absolute_url(self):
        return reverse("messaging:thread", args=[self.pk])

    def participants(self):
        return (self.buyer_id, self.owner_id)

    def is_participant(self, user):
        return user.is_authenticated and user.pk in self.participants()

    def other(self, user):
        return self.owner if user.pk == self.buyer_id else self.buyer


class Message(models.Model):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_sent")
    body = models.TextField(_("message"), max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Message {self.pk} in {self.thread_id}"


class MessageRead(models.Model):
    """Per-user read marker for a thread, plus when we last emailed them about it."""

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_reads")
    last_read_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["thread", "user"], name="one_read_marker_per_user")]
