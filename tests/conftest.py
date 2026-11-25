import itertools
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Profile, User
from apps.listings.geo import make_point
from apps.listings.models import Listing, ListingLocation, ListingStatus
from config.celery import app as celery_app

PASSWORD = "Correct-Horse-42"
_counter = itertools.count()


@pytest.fixture(scope="session")
def _media_root(tmp_path_factory):
    # Shared across the session so generated seed photos are reused between tests.
    return tmp_path_factory.mktemp("media")


@pytest.fixture(autouse=True)
def _test_env(settings, _media_root):
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.MEDIA_ROOT = str(_media_root)
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def make_user(db):
    def _make(verified=True, **flags):
        n = next(_counter)
        user = User.objects.create_user(
            email=flags.pop("email", f"user{n}@test.example"),
            password=PASSWORD,
            full_name=flags.pop("full_name", f"Test User {n}"),
            email_verified_at=timezone.now() if verified else None,
            **flags,
        )
        Profile.objects.create(user=user)
        return user

    return _make


@pytest.fixture
def make_listing(db):
    def _make(owner, lat=-1.2921, lng=36.8219, status=ListingStatus.PUBLISHED, **fields):
        listing = Listing.objects.create(
            owner=owner,
            title=fields.pop("title", "Test home"),
            description="A home for tests.",
            property_type=fields.pop("property_type", "apartment"),
            purpose=fields.pop("purpose", "sale"),
            price=fields.pop("price", Decimal("150000")),
            city=fields.pop("city", "Nairobi"),
            country=fields.pop("country", "Kenya"),
            status=status,
            published_at=timezone.now() if status == ListingStatus.PUBLISHED else None,
            **fields,
        )
        ListingLocation.objects.create(listing=listing, point=make_point(lat, lng))
        return listing

    return _make
