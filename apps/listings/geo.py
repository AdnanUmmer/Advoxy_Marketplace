"""PostGIS queries for listings."""

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.measure import D

from .models import Listing


def make_point(lat, lng):
    return Point(float(lng), float(lat), srid=4326)


def within_radius(queryset, lat, lng, km):
    """Listings whose pin is within `km` kilometres of (lat, lng), nearest first.

    Uses ST_DWithin on geography, which is index-assisted and measured in metres.
    """
    center = make_point(lat, lng)
    return (
        queryset.filter(location__point__dwithin=(center, D(km=float(km))))
        .annotate(distance=Distance("location__point", center))
        .order_by("distance")
    )


def within_polygon(queryset, coords):
    """Listings inside a drawn area. `coords` is a list of (lng, lat) pairs."""
    ring = [tuple(map(float, c)) for c in coords]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    area = Polygon(ring, srid=4326)
    return queryset.filter(location__point__intersects=area)


def published_listings():
    return Listing.objects.published().select_related("location").prefetch_related("photos")
