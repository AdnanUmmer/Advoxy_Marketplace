"""Seed command, public pages, brand and currency configuration."""

from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from django.template import Context, Template
from django.urls import reverse

from apps.accounts.models import AgencyTeam, Role, User
from apps.core.management.commands.seed_demo import DEMO_DOMAIN, DEMO_PASSWORD
from apps.listings.models import Listing, ListingStatus
from config.brand import BRAND

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_demo")


def test_seed_creates_listings_across_cities(seeded):
    assert Listing.objects.count() >= 60
    assert Listing.objects.values("city").distinct().count() >= 8
    assert Listing.objects.published().count() >= 50
    assert all(l.photos.count() >= 1 and hasattr(l, "location") for l in Listing.objects.all()[:10])


def test_seed_creates_every_role(seeded):
    demo = User.objects.filter(email__endswith=DEMO_DOMAIN)
    for role in Role:
        assert any(u.has_role(role) for u in demo), role
    agency = AgencyTeam.objects.get(owner__email=f"agency@{DEMO_DOMAIN}")
    assert agency.agents.count() == 3


def test_seed_respects_individual_free_limits(seeded):
    active = Listing.objects.filter(status=ListingStatus.PUBLISHED)
    assert active.filter(owner__email=f"seller@{DEMO_DOMAIN}").count() <= 1
    assert active.filter(owner__email=f"landlord@{DEMO_DOMAIN}").count() <= 2


def test_seed_accounts_can_sign_in(seeded, client):
    assert client.login(username=f"buyer@{DEMO_DOMAIN}", password=DEMO_PASSWORD)


def test_seed_refuses_to_duplicate_without_reset(seeded):
    with pytest.raises(CommandError):
        call_command("seed_demo")
    call_command("seed_demo", "--reset")
    assert User.objects.filter(email=f"buyer@{DEMO_DOMAIN}").count() == 1


@pytest.mark.parametrize("name", ["core:home", "core:about", "core:contact", "core:help", "search:results",
                                  "accounts:login", "accounts:signup", "accounts:password_reset", "accounts:staff_login"])
def test_public_pages_render(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 200
    assert BRAND["name"] in response.content.decode()


def test_home_and_detail_with_seed(seeded, client):
    home = client.get(reverse("core:home"))
    assert home.status_code == 200 and "Nairobi" in home.content.decode()
    listing = Listing.objects.published().first()
    assert client.get(listing.get_absolute_url()).status_code == 200


def test_unpublished_listing_hidden_from_public(client, make_user, make_listing):
    draft = make_listing(make_user(is_seller=True), status=ListingStatus.DRAFT)
    assert client.get(draft.get_absolute_url()).status_code == 404


def test_search_filters_by_city_and_purpose(client, make_user, make_listing):
    owner = make_user(is_agent=True)
    make_listing(owner, city="Accra", purpose="rent", title="Accra rental")
    make_listing(owner, city="Accra", purpose="sale", title="Accra sale")
    make_listing(owner, city="Cairo", purpose="rent", title="Cairo rental")
    response = client.get(reverse("search:results"), {"city": "accra", "purpose": "rent"})
    assert [l.title for l in response.context["page"].object_list] == ["Accra rental"]


def test_money_filter_uses_currency_settings(settings):
    settings.CURRENCY_SYMBOL = "$"
    out = Template("{% load ui %}{{ v|money }}").render(Context({"v": Decimal("1250000")}))
    assert out == "$1,250,000"
    settings.CURRENCY_SYMBOL = "€"
    assert Template("{% load ui %}{{ v|money }}").render(Context({"v": 900})) == "€900"


def test_demo_banner_controlled_by_flag(client, settings):
    settings.DEMO_MODE = False
    assert "Demo site." not in client.get(reverse("core:home")).content.decode()
    settings.DEMO_MODE = True
    assert "Demo site." in client.get(reverse("core:home")).content.decode()
