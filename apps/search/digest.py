"""Daily saved-search digest: one email per user listing new matches for each of their searches."""

from collections import defaultdict

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.emails import send_templated_email

from . import filters
from .models import SavedSearch

MAX_PER_SEARCH = 6


def new_matches(saved, since):
    """Listings matching a saved search that were published after `since`."""
    _form, qs, _center = filters.search(saved.query)
    return list(qs.filter(published_at__gt=since).prefetch_related("photos")[: MAX_PER_SEARCH + 1])


def send_digests(now=None):
    """Returns the number of emails queued."""
    now = now or timezone.now()
    by_user = defaultdict(list)
    searches = (
        SavedSearch.objects.filter(email_alerts=True, user__is_active=True, user__is_suspended=False,
                                   user__email_verified_at__isnull=False)
        .select_related("user")
        .order_by("user_id", "created_at")
    )
    touched = []
    for saved in searches:
        since = saved.last_notified_at or saved.created_at
        matches = new_matches(saved, since)
        touched.append(saved.pk)
        if matches:
            by_user[saved.user].append({
                "name": saved.name,
                "listings": matches[:MAX_PER_SEARCH],
                "more": len(matches) > MAX_PER_SEARCH,
                "url": reverse("search:results") + (f"?{saved.query}" if saved.query else ""),
            })
    for user, sections in by_user.items():
        send_templated_email("saved_search_digest", user.email, {
            "user_name": user.get_short_name(),
            "sections": sections,
            "total": sum(len(s["listings"]) for s in sections),
            "manage_url": reverse("search:saved"),
        })
    with transaction.atomic():
        SavedSearch.objects.filter(pk__in=touched).update(last_notified_at=now)
    return len(by_user)
