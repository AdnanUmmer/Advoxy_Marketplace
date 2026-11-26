"""Query counts must not grow with the number of rows shown (no N+1 queries). Milestone 8 performance pass."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import AgencyTeam, AgentProfile
from apps.listings.models import ListingPhoto

pytestmark = pytest.mark.django_db


def count(client, url):
    client.get(url)  # warm caches (site settings, content types)
    with CaptureQueriesContext(connection) as ctx:
        assert client.get(url).status_code == 200
    return len(ctx.captured_queries)


@pytest.fixture
def grow(make_user, make_listing):
    owner = make_user(email="agency@example.com", is_agency=True)
    agency = AgencyTeam.objects.create(owner=owner, name="Scale Homes")
    agents = []

    def _add(n):
        for _ in range(n):
            agent = make_user(is_agent=True)
            AgentProfile.objects.create(user=agent, agency=agency)
            agents.append(agent)
            listing = make_listing(agent, agency=agency)
            ListingPhoto.objects.create(listing=listing, image="listings/missing.jpg", thumbnail="listings/thumbs/missing.jpg")
        return agency, agents
    return _add


@pytest.mark.parametrize("url_name", ["core:home", "search:results", "agencies:agents", "agencies:agencies"])
def test_public_lists_do_not_scale_queries(client, grow, url_name):
    grow(3)
    small = count(client, reverse(url_name))
    grow(9)
    assert count(client, reverse(url_name)) == small


def test_agency_page_does_not_scale_queries(client, grow):
    agency, _ = grow(3)
    url = reverse("agencies:agency", args=[agency.slug])
    small = count(client, url)
    grow(9)
    assert count(client, url) == small


@pytest.mark.parametrize("url_name", ["staff:listings", "staff:users", "staff:moderation", "staff:overview", "staff:audit"])
def test_staff_tables_do_not_scale_queries(client, make_user, grow, url_name):
    client.force_login(make_user(is_staff=True))
    grow(3)
    small = count(client, reverse(url_name))
    grow(9)
    assert count(client, reverse(url_name)) == small
