"""Search filters, PostGIS radius/area search through the page, favorites, saved searches and the digest."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.listings.models import Amenity, ListingStatus
from apps.search import filters
from apps.search.digest import send_digests
from apps.search.models import Favorite, SavedSearch

pytestmark = pytest.mark.django_db
URL = "/search/"


def titles(response):
    return [l.title for l in response.context["page"].object_list]


@pytest.fixture
def agent(make_user):
    return make_user(is_agent=True)


@pytest.fixture
def catalogue(agent, make_listing):
    pool = Amenity.objects.create(name="Swimming pool", slug="swimming-pool")
    gym = Amenity.objects.create(name="Gym", slug="gym")
    a = make_listing(agent, -1.2676, 36.8108, title="Westlands flat", city="Nairobi", neighborhood="Westlands",
                     purpose="rent", price=Decimal("1500"), bedrooms=2, bathrooms=1, area_sqm=80, furnished=True)
    b = make_listing(agent, -1.3197, 36.7073, title="Karen villa", city="Nairobi", neighborhood="Karen",
                     property_type="villa", purpose="sale", price=Decimal("900000"), bedrooms=5, bathrooms=4, area_sqm=420)
    c = make_listing(agent, 6.4520, 3.4350, title="Ikoyi apartment", city="Lagos", neighborhood="Ikoyi",
                     purpose="sale", price=Decimal("350000"), bedrooms=3, bathrooms=2, area_sqm=160, is_featured=True)
    d = make_listing(agent, -1.2921, 36.7856, title="Kilimani townhouse", city="Nairobi", neighborhood="Kilimani",
                     property_type="townhouse", purpose="rent", price=Decimal("2600"), bedrooms=3, bathrooms=3, area_sqm=200)
    make_listing(agent, -1.2900, 36.8000, title="Draft home", city="Nairobi", status=ListingStatus.DRAFT)
    a.amenities.set([pool, gym]); b.amenities.set([pool]); d.amenities.set([gym])
    return {"a": a, "b": b, "c": c, "d": d}


# --- filters --------------------------------------------------------------------
@pytest.mark.parametrize("params, expected", [
    ({"purpose": "rent"}, {"Westlands flat", "Kilimani townhouse"}),
    ({"city": "nairobi"}, {"Westlands flat", "Karen villa", "Kilimani townhouse"}),
    ({"neighborhood": "kar"}, {"Karen villa"}),
    ({"type": ["villa", "townhouse"]}, {"Karen villa", "Kilimani townhouse"}),
    ({"price_min": "1000", "price_max": "3000"}, {"Westlands flat", "Kilimani townhouse"}),
    ({"price_min": "3000", "price_max": "1000"}, {"Westlands flat", "Kilimani townhouse"}),  # swapped bounds
    ({"beds": "3"}, {"Karen villa", "Ikoyi apartment", "Kilimani townhouse"}),
    ({"baths": "3"}, {"Karen villa", "Kilimani townhouse"}),
    ({"area_min": "150", "area_max": "250"}, {"Ikoyi apartment", "Kilimani townhouse"}),
    ({"furnished": "yes"}, {"Westlands flat"}),
    ({"amenities": ["swimming-pool", "gym"]}, {"Westlands flat"}),  # must have all
    ({"amenities": ["gym"]}, {"Westlands flat", "Kilimani townhouse"}),
    ({"beds": "abc", "price_min": "-5"}, {"Westlands flat", "Karen villa", "Ikoyi apartment", "Kilimani townhouse"}),
])
def test_filters(client, catalogue, params, expected):
    assert set(titles(client.get(URL, params))) == expected


def test_drafts_never_appear(client, catalogue):
    assert "Draft home" not in titles(client.get(URL))


@pytest.mark.parametrize("sort, first", [
    ("featured", "Ikoyi apartment"), ("price_asc", "Westlands flat"), ("price_desc", "Karen villa"),
])
def test_sorting(client, catalogue, sort, first):
    assert titles(client.get(URL, {"sort": sort}))[0] == first


def test_pagination(client, agent, make_listing):
    for i in range(30):
        make_listing(agent, title=f"Home {i}")
    first = client.get(URL)
    assert first.context["total"] == 30 and len(first.context["page"].object_list) == 24
    assert len(client.get(URL, {"page": 2}).context["page"].object_list) == 6


# --- PostGIS through the search page ----------------------------------------------
def test_radius_from_point(client, catalogue):
    # 5 km around Nairobi CBD: Westlands (~2 km) and Kilimani (~3.5 km), not Karen (~13 km)
    response = client.get(URL, {"near": "-1.2864,36.8172", "radius": "5", "sort": "newest"})
    assert set(titles(response)) == {"Westlands flat", "Kilimani townhouse"}


def test_radius_from_city_centre_without_map(client, catalogue):
    response = client.get(URL, {"city": "Nairobi", "radius": "50"})
    assert set(titles(response)) == {"Westlands flat", "Karen villa", "Kilimani townhouse"}
    assert response.context["center"] is not None


def test_radius_featured_sort_uses_distance(client, catalogue):
    response = client.get(URL, {"near": "-1.2676,36.8108", "radius": "25"})
    assert titles(response)[0] == "Westlands flat"  # nearest first


def test_drawn_area(client, catalogue):
    area = "36.70,-1.33;36.80,-1.33;36.80,-1.28;36.70,-1.28"  # Karen + Kilimani, not Westlands
    assert set(titles(client.get(URL, {"area": area}))) == {"Karen villa", "Kilimani townhouse"}


@pytest.mark.parametrize("area", ["1,2;3,4", "garbage", "200,1;201,1;202,2", "0,0;1,1;0,1;1,0"])
def test_invalid_area_is_ignored(client, catalogue, area):
    assert len(titles(client.get(URL, {"area": area}))) == 4


def test_map_pins_and_partial(client, catalogue):
    response = client.get(URL, {"city": "Lagos"}, HTTP_HX_REQUEST="true")
    assert [t.name for t in response.templates][0] == "search/_results.html"
    pins = json.loads(response.content.decode().split('id="map-pins" type="application/json">')[1].split("</script>")[0])
    assert pins == [{
        "id": catalogue["c"].pk, "lat": 6.452, "lng": 3.435, "price": "$350K", "title": "Ikoyi apartment",
        "url": catalogue["c"].get_absolute_url(), "photo": "", "beds": 3, "baths": 2, "featured": True, "rent": False,
    }]


@pytest.mark.parametrize("amount, label", [(1800, "$1,800"), (85000, "$85,000"), (350000, "$350K"), (1250000, "$1.25M"), (2000000, "$2M")])
def test_short_price(amount, label):
    assert filters.short_price(amount) == label


def test_renter_defaults_to_rentals(client, catalogue, make_user):
    client.force_login(make_user(is_renter=True))
    assert set(titles(client.get(URL))) == {"Westlands flat", "Kilimani townhouse"}
    assert len(titles(client.get(URL, {"purpose": ""}))) == 4  # explicit choice wins


# --- favorites -----------------------------------------------------------------------
def test_favorite_toggle(client, catalogue, make_user):
    user = make_user(is_buyer=True)
    client.force_login(user)
    url = reverse("search:favorite_toggle", args=[catalogue["a"].pk])
    response = client.post(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and 'aria-pressed="true"' in response.content.decode()
    assert Favorite.objects.filter(user=user, listing=catalogue["a"]).exists()
    client.post(url, HTTP_HX_REQUEST="true")
    assert not Favorite.objects.filter(user=user).exists()


def test_favorites_show_on_cards_and_pages(client, catalogue, make_user):
    user = make_user(is_buyer=True)
    Favorite.objects.create(user=user, listing=catalogue["b"])
    client.force_login(user)
    html = client.get(URL, {"city": "Nairobi", "sort": "price_desc"}).content.decode()
    assert html.count('aria-pressed="true"') == 1
    assert [l.title for l in client.get(reverse("search:favorites")).context["listings"]] == ["Karen villa"]
    dash = client.get(reverse("accounts:dashboard"))
    assert [l.title for l in dash.context["favorite_listings"]] == ["Karen villa"]


def test_favorites_require_verified_account(client, catalogue, make_user):
    url = reverse("search:favorite_toggle", args=[catalogue["a"].pk])
    assert reverse("accounts:login") in client.post(url).url
    client.force_login(make_user(is_buyer=True, verified=False))
    assert client.post(url).url == reverse("accounts:verify_email_sent")
    assert not Favorite.objects.exists()


def test_cannot_favorite_unpublished(client, agent, make_listing, make_user):
    draft = make_listing(agent, status=ListingStatus.DRAFT)
    client.force_login(make_user(is_buyer=True))
    assert client.post(reverse("search:favorite_toggle", args=[draft.pk])).status_code == 404


# --- saved searches ---------------------------------------------------------------------
def test_save_search(client, catalogue, make_user):
    user = make_user(is_buyer=True)
    client.force_login(user)
    response = client.post(reverse("search:saved_create"), {"query": "purpose=rent&city=nairobi&beds=2&page=3&csrf=x"})
    saved = SavedSearch.objects.get(user=user)
    assert saved.query == "purpose=rent&city=nairobi&beds=2"
    assert saved.name == "Rent · Nairobi · 2+ beds"
    assert response.url == "/search/?purpose=rent&city=nairobi&beds=2"
    client.post(reverse("search:saved_create"), {"query": "purpose=rent&city=nairobi&beds=2"})
    assert SavedSearch.objects.filter(user=user).count() == 1
    page = client.get(URL, {"purpose": "rent", "city": "nairobi", "beds": "2"})
    assert page.context["already_saved"]


def test_toggle_and_delete_saved_search(client, make_user):
    user, other = make_user(), make_user()
    mine = SavedSearch.objects.create(user=user, name="x", query="city=Accra")
    theirs = SavedSearch.objects.create(user=other, name="y", query="city=Cairo")
    client.force_login(user)
    client.post(reverse("search:saved_update", args=[mine.pk, "alerts"]), HTTP_HX_REQUEST="true")
    mine.refresh_from_db()
    assert mine.email_alerts is False
    assert client.post(reverse("search:saved_update", args=[theirs.pk, "delete"])).status_code == 404
    client.post(reverse("search:saved_update", args=[mine.pk, "delete"]))
    assert not SavedSearch.objects.filter(pk=mine.pk).exists()


# --- daily digest --------------------------------------------------------------------------
def test_digest_sends_only_new_matches_once(catalogue, make_user, make_listing, agent):
    user = make_user(email="alerts@example.com")
    yesterday = timezone.now() - timedelta(days=1)
    SavedSearch.objects.create(user=user, name="Rent · Nairobi", query="purpose=rent&city=Nairobi", last_notified_at=yesterday)
    SavedSearch.objects.create(user=user, name="Lagos", query="city=Lagos", last_notified_at=yesterday)
    for l in catalogue.values():
        l.published_at = yesterday - timedelta(days=1)
        l.save()
    fresh = make_listing(agent, -1.28, 36.80, title="Fresh rental", city="Nairobi", purpose="rent")
    make_listing(agent, -1.28, 36.80, title="Fresh sale", city="Nairobi", purpose="sale")

    assert send_digests() == 1
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert mail.outbox[0].to == ["alerts@example.com"]
    assert "Fresh rental" in body and fresh.get_absolute_url() in body
    assert "Fresh sale" not in body and "Westlands flat" not in body and "Lagos" not in body
    assert "1 new home" in mail.outbox[0].subject

    assert send_digests() == 0  # nothing new since the last run
    assert len(mail.outbox) == 1


def test_digest_skips_disabled_and_unverified(catalogue, make_user, make_listing, agent):
    old = timezone.now() - timedelta(days=30)
    SavedSearch.objects.create(user=make_user(), name="off", query="", email_alerts=False, last_notified_at=old)
    SavedSearch.objects.create(user=make_user(verified=False), name="unverified", query="", last_notified_at=old)
    assert send_digests() == 0 and len(mail.outbox) == 0


def test_htmx_pushes_clean_url(client, catalogue):
    response = client.get(URL, {"city": "Lagos", "beds": "", "sort": "featured", "area": ""}, HTTP_HX_REQUEST="true")
    assert response["HX-Push-Url"] == "/search/?city=Lagos"


# --- layout and priority markets ---------------------------------------------------------
def test_popular_cities_follow_priority_countries(make_user, make_listing, settings):
    from apps.listings.markets import popular_cities

    settings.PRIORITY_COUNTRIES = ["Nigeria", "Kenya"]
    owner = make_user(is_agent=True)
    for _ in range(3):
        make_listing(owner, city="Cairo", country="Egypt")  # biggest, but not a priority market
    make_listing(owner, city="Nairobi", country="Kenya")
    make_listing(owner, city="Lagos", country="Nigeria")
    assert [c["city"] for c in popular_cities()] == ["Lagos", "Nairobi", "Cairo"]


@pytest.mark.parametrize("params, heading", [
    ({"purpose": "rent", "city": "lagos"}, "Properties for rent in Lagos"),
    ({"purpose": "sale"}, "Properties for sale"),
    ({}, "Properties across Africa"),
])
def test_search_heading(client, catalogue, params, heading):
    assert client.get(URL, params).context["heading"] == heading


def test_result_cards_show_full_details(client, catalogue):
    html = client.get(URL, {"city": "Nairobi", "type": "villa"}).content.decode()
    for text in ("Karen villa", "$900,000", "Villa", "5 beds", "4 baths", "420 m²", "Karen, Nairobi, Kenya", "Swimming pool", "#contact"):
        assert text in html, text


def test_home_hero_has_bayut_style_filters(client, catalogue):
    html = client.get("/").content.decode()
    for text in ("Property type", "Beds & baths", "Price (USD)", 'name="beds"', 'name="price_max"', 'name="type"'):
        assert text in html, text
