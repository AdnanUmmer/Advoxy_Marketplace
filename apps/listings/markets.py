"""Priority markets: cities and countries are listed in settings.PRIORITY_COUNTRIES order first."""

from django.conf import settings
from django.db.models import Case, Count, IntegerField, Value, When

from .models import Listing


def country_priority(field="country"):
    countries = settings.PRIORITY_COUNTRIES
    return Case(
        *[When(**{field: c}, then=Value(i)) for i, c in enumerate(countries)],
        default=Value(len(countries)),
        output_field=IntegerField(),
    )


def popular_cities(limit=12, purpose=None):
    """[{'city', 'country', 'total'}] for published listings, priority countries first."""
    qs = Listing.objects.published()
    if purpose:
        qs = qs.filter(purpose=purpose)
    return list(
        qs.values("city", "country")
        .annotate(total=Count("id"), rank=country_priority())
        .order_by("rank", "-total", "city")[:limit]
    )
