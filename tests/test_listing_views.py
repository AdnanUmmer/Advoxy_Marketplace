"""Create/edit listing pages, photo manager, detail page and owner dashboard."""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.listings.models import Amenity, Listing, ListingPhoto, ListingStatus

pytestmark = pytest.mark.django_db
S = ListingStatus


def jpeg(name="photo.jpg", size=(2600, 1800), exif_gps=False):
    img = Image.new("RGB", size, (180, 150, 120))
    buf = BytesIO()
    kwargs = {}
    if exif_gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (1.0, 17.0, 0.0)}  # GPSInfo
        exif[0x010F] = "PhoneMaker"
        kwargs["exif"] = exif
    img.save(buf, "JPEG", **kwargs)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def form_data(**overrides):
    data = {
        "title": "  Garden   flat in Kilimani ",
        "purpose": "rent",
        "property_type": "apartment",
        "price": "1200",
        "description": "Two bedrooms, quiet street.",
        "bedrooms": "2",
        "bathrooms": "1",
        "area_sqm": "85",
        "city": "Nairobi",
        "country": "Kenya",
        "neighborhood": "Kilimani",
        "address": "",
        "latitude": "-1.292100",
        "longitude": "36.785600",
    }
    data.update(overrides)
    return data


@pytest.fixture
def landlord(client, make_user):
    user = make_user(is_landlord=True)
    client.force_login(user)
    return user


# --- create -------------------------------------------------------------------
def test_create_listing_with_photos(client, landlord):
    pool = Amenity.objects.create(name="Pool", slug="pool")
    data = form_data(amenities=[pool.pk], photos=[jpeg("a.jpg"), jpeg("b.jpg", exif_gps=True)])
    response = client.post(reverse("listings:create"), data)
    listing = Listing.objects.get(owner=landlord)
    assert response.status_code == 302 and response.url == reverse("listings:edit", args=[listing.pk])
    assert listing.status == S.DRAFT and listing.title == "Garden flat in Kilimani"
    assert listing.slug == "garden-flat-in-kilimani"
    assert list(listing.amenities.all()) == [pool]
    assert round(listing.location.latitude, 4) == -1.2921 and round(listing.location.longitude, 4) == 36.7856
    photos = list(listing.photos.all())
    assert [p.position for p in photos] == [0, 1]
    with Image.open(photos[1].image.path) as img:
        assert max(img.size) == 2000  # downscaled
        assert not img.getexif()  # EXIF (incl. GPS) stripped


def test_create_validates_fields(client, landlord):
    response = client.post(reverse("listings:create"), form_data(price="0", latitude="123", property_type="land"))
    errors = response.context["form"].errors
    assert {"price", "latitude", "property_type"} <= errors.keys()  # land is not offered in phase 1
    assert not Listing.objects.exists()


def test_create_rejects_non_images(client, landlord):
    bad = SimpleUploadedFile("notes.jpg", b"not an image", content_type="image/jpeg")
    client.post(reverse("listings:create"), form_data(photos=[bad]))
    listing = Listing.objects.get(owner=landlord)
    assert listing.photos.count() == 0  # draft saved, photo refused with a message


def test_buyers_cannot_create(client, make_user):
    client.force_login(make_user(is_buyer=True))
    assert client.get(reverse("listings:create")).status_code == 403


def test_unverified_owner_is_sent_to_verify(client, make_user):
    client.force_login(make_user(is_seller=True, verified=False))
    response = client.get(reverse("listings:create"))
    assert response.status_code == 302 and response.url == reverse("accounts:verify_email_sent")


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("listings:create"))
    assert response.status_code == 302 and reverse("accounts:login") in response.url


# --- edit ---------------------------------------------------------------------
def test_owner_edits_and_live_listing_returns_to_review(client, landlord, make_listing):
    listing = make_listing(landlord, purpose="rent", status=S.PUBLISHED)
    response = client.post(reverse("listings:edit", args=[listing.pk]), form_data(title="New title", price="1500"))
    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.title == "New title" and listing.slug == "new-title" and listing.status == S.PENDING


def test_edit_without_changes_keeps_listing_live(client, landlord, make_listing):
    listing = make_listing(landlord, purpose="rent", status=S.PUBLISHED, title="Same", price=1200,
                           description="Two bedrooms, quiet street.", bedrooms=2, bathrooms=1, area_sqm=85,
                           neighborhood="Kilimani")
    listing.location.point.y, listing.location.point.x = -1.2921, 36.7856
    data = form_data(title="Same")
    page = client.get(reverse("listings:edit", args=[listing.pk]))
    initial = page.context["form"].initial
    data.update(latitude=str(initial["latitude"]), longitude=str(initial["longitude"]))
    client.post(reverse("listings:edit", args=[listing.pk]), data)
    listing.refresh_from_db()
    assert listing.status == S.PUBLISHED


def test_other_users_cannot_edit(client, make_user, make_listing, landlord):
    listing = make_listing(make_user(is_landlord=True), status=S.DRAFT)
    assert client.get(reverse("listings:edit", args=[listing.pk])).status_code == 404
    assert client.post(reverse("listings:transition", args=[listing.pk, "submit"])).status_code == 404


def test_transition_view_reports_limit(client, landlord, make_listing):
    for _ in range(2):
        make_listing(landlord, purpose="rent", status=S.PUBLISHED)
    draft = make_listing(landlord, purpose="rent", status=S.DRAFT)
    ListingPhoto.objects.create(listing=draft, image="seed/x.jpg")
    response = client.post(reverse("listings:transition", args=[draft.pk, "submit"]), follow=True)
    assert "active listing slots" in response.content.decode()
    draft.refresh_from_db()
    assert draft.status == S.DRAFT


def test_transition_requires_post(client, landlord, make_listing):
    listing = make_listing(landlord, status=S.DRAFT)
    assert client.get(reverse("listings:transition", args=[listing.pk, "remove"])).status_code == 405


# --- photo manager --------------------------------------------------------------
def test_photo_upload_reorder_cover_and_delete(client, landlord, make_listing, django_capture_on_commit_callbacks):
    listing = make_listing(landlord, status=S.DRAFT)
    url = reverse("listings:photo_upload", args=[listing.pk])
    response = client.post(url, {"photos": [jpeg("1.jpg"), jpeg("2.jpg"), jpeg("3.jpg")]}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and "listings/_photo_manager.html" in [t.name for t in response.templates]
    a, b, c = listing.photos.all()

    client.post(reverse("listings:photo_reorder", args=[listing.pk]), {"order": [c.pk, a.pk, b.pk]}, HTTP_HX_REQUEST="true")
    assert list(listing.photos.values_list("pk", flat=True)) == [c.pk, a.pk, b.pk]

    client.post(reverse("listings:photo_action", args=[listing.pk, b.pk, "cover"]), HTTP_HX_REQUEST="true")
    assert listing.cover.pk == b.pk

    client.post(reverse("listings:photo_action", args=[listing.pk, b.pk, "down"]), HTTP_HX_REQUEST="true")
    assert list(listing.photos.values_list("pk", flat=True)) == [c.pk, b.pk, a.pk]

    path = b.image.path
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("listings:photo_action", args=[listing.pk, b.pk, "delete"]), HTTP_HX_REQUEST="true")
    assert list(listing.photos.values_list("position", flat=True)) == [0, 1]
    import os
    assert not os.path.exists(path)


def test_photo_limit(client, landlord, make_listing, monkeypatch):
    from apps.listings import photos
    monkeypatch.setattr(photos, "MAX_PHOTOS", 2)
    listing = make_listing(landlord, status=S.DRAFT)
    response = client.post(reverse("listings:photo_upload", args=[listing.pk]), {"photos": [jpeg(), jpeg(), jpeg()]})
    assert "up to 2 photos" in response.content.decode() and listing.photos.count() == 0


def test_photo_endpoints_are_owner_only(client, make_user, make_listing, landlord):
    other_listing = make_listing(make_user(is_landlord=True), status=S.DRAFT)
    assert client.post(reverse("listings:photo_upload", args=[other_listing.pk]), {"photos": [jpeg()]}).status_code == 404


# --- detail page ------------------------------------------------------------------
def test_detail_page_shows_gallery_facts_and_similar(client, make_user, make_listing):
    agent = make_user(is_agent=True, full_name="Grace Agent")
    listing = make_listing(agent, title="Main home", price=200000, bedrooms=3)
    for i in range(3):
        ListingPhoto.objects.create(listing=listing, image=f"seed/p{i}.jpg", position=i, alt_text=f"Room {i}")
    near = make_listing(agent, -1.29, 36.82, title="Nearby home", price=210000)
    make_listing(agent, -1.29, 36.82, title="Too pricey", price=9000000)
    make_listing(agent, -1.29, 36.82, title="A rental", purpose="rent", price=1000)
    response = client.get(listing.get_absolute_url())
    html = response.content.decode()
    assert response.status_code == 200
    assert "Main home" in html and "Grace Agent" in html and 'alt="Room 2"' in html
    assert [s.title for s in response.context["similar"]][0] == near.title
    assert "Too pricey" not in [s.title for s in response.context["similar"][:1]]
    assert "A rental" not in [s.title for s in response.context["similar"]]


def test_owner_can_preview_draft_but_public_cannot(client, make_user, make_listing):
    owner = make_user(is_seller=True)
    draft = make_listing(owner, status=S.DRAFT)
    assert client.get(draft.get_absolute_url()).status_code == 404
    client.force_login(owner)
    response = client.get(draft.get_absolute_url())
    assert response.status_code == 200 and response.context["preview"]


def test_wrong_slug_redirects(client, make_user, make_listing):
    listing = make_listing(make_user(is_agent=True))
    response = client.get(reverse("listings:detail", args=[listing.pk, "old-slug"]))
    assert response.status_code == 301 and response.url == listing.get_absolute_url()


# --- dashboard ----------------------------------------------------------------------
def test_owner_dashboard_tabs_and_capacity(client, landlord, make_listing):
    make_listing(landlord, purpose="rent", status=S.PUBLISHED, title="Live one")
    make_listing(landlord, purpose="rent", status=S.DRAFT, title="Draft one")
    response = client.get(reverse("accounts:dashboard"))
    tabs = {k: n for k, _l, n in response.context["tabs"]}
    assert tabs == {"all": 2, "draft": 1, "review": 0, "live": 1, "closed": 0}
    assert response.context["capacity"].used == 1 and response.context["capacity"].total == 2
    drafts = client.get(reverse("accounts:dashboard") + "?as=landlord&tab=draft")
    assert [l.title for l, _a in drafts.context["rows"]] == ["Draft one"]
