"""PostGIS: radius search and drawn-area search on listing pins."""

import pytest
from django.db import connection

from apps.listings.geo import published_listings, within_polygon, within_radius
from apps.listings.models import Listing, ListingStatus

pytestmark = pytest.mark.django_db

# Nairobi CBD
CBD = (-1.2864, 36.8172)


def test_postgis_extension_is_installed():
    with connection.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'postgis'")
        assert cur.fetchone() is not None


@pytest.fixture
def nairobi_listings(make_user, make_listing):
    owner = make_user(is_agent=True)
    return {
        "westlands": make_listing(owner, -1.2676, 36.8108, title="Westlands"),     # ~2.2 km from CBD
        "karen": make_listing(owner, -1.3197, 36.7073, title="Karen"),             # ~12.7 km
        "thika": make_listing(owner, -1.0333, 37.0693, title="Thika"),             # ~40 km
        "draft": make_listing(owner, -1.2870, 36.8180, title="Draft", status=ListingStatus.DRAFT),
        "lagos": make_listing(owner, 6.4520, 3.4350, title="Lagos", city="Lagos"),
    }


def test_radius_includes_only_points_inside(nairobi_listings):
    titles = [l.title for l in within_radius(Listing.objects.all(), *CBD, km=5)]
    assert titles == ["Draft", "Westlands"]  # nearest first


def test_radius_grows_with_distance_and_orders_by_distance(nairobi_listings):
    results = list(within_radius(Listing.objects.published(), *CBD, km=15))
    assert [l.title for l in results] == ["Westlands", "Karen"]
    assert results[0].distance.km < results[1].distance.km
    assert 1.5 < results[0].distance.km < 3.0
    assert 11 < results[1].distance.km < 14


def test_radius_combines_with_other_filters(nairobi_listings):
    assert within_radius(published_listings(), *CBD, km=50).count() == 3  # draft excluded, Lagos far away


def test_drawn_area_polygon(nairobi_listings):
    # Box around central and western Nairobi (lng, lat)
    box = [(36.70, -1.33), (36.85, -1.33), (36.85, -1.25), (36.70, -1.25)]
    titles = set(within_polygon(Listing.objects.published(), box).values_list("title", flat=True))
    assert titles == {"Westlands", "Karen"}
