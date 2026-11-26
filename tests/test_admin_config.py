"""Milestone 8: admin settings (editable without code), plans, audit log, email previews."""

import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.urls import reverse
from PIL import Image

from apps.billing import services as billing
from apps.billing.models import Plan
from apps.core import site_settings
from apps.core.models import AuditLog, Setting
from apps.listings import rules
from apps.listings.models import ListingStatus
from apps.staff.config_views import _sample_contexts

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(make_user):
    return make_user(email="staff@example.com", is_staff=True)


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


def _site_post(**overrides):
    data = {"section": "site", **{k: str(v) for k, v in site_settings.all_values().items() if k != "logo"}}
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Settings store
# ---------------------------------------------------------------------------
def test_defaults_come_from_config():
    assert site_settings.get("currency_code") == "USD"
    assert site_settings.get("featured_price") == Decimal("25")
    assert site_settings.get("free_seller_listings") == 1


def test_save_records_only_changes_and_clears_cache():
    assert site_settings.save({"featured_price": "25"}) == {}
    diff = site_settings.save({"featured_price": "40", "featured_days": 7})
    assert diff == {"featured_price": ("25", "40"), "featured_days": (14, 7)}
    assert site_settings.get("featured_price") == Decimal("40")
    assert Setting.objects.count() == 2


def test_free_limits_follow_settings(make_user):
    seller = make_user(is_seller=True)
    assert rules.capacity_for(seller).free == 1
    site_settings.save({"free_seller_listings": 3})
    assert rules.capacity_for(seller).free == 3


def test_listing_lifetime_follows_settings(make_user, make_listing, staff):
    from datetime import timedelta

    site_settings.save({"listing_lifetime_days": 30})
    listing = make_listing(make_user(is_seller=True), status=ListingStatus.PENDING)
    rules.moderate(listing, staff, "approve")
    listing.refresh_from_db()
    assert listing.expires_at - listing.published_at == timedelta(days=30)


def test_prices_follow_settings(make_user, make_listing, monkeypatch):
    from types import SimpleNamespace

    from apps.billing.models import Purchase

    sent = {}

    class FakeProvider:
        def create_checkout(self, request):
            sent["request"] = request
            return SimpleNamespace(session_id="cs_test", url="https://checkout.example/x")

    monkeypatch.setattr(billing, "get_provider", lambda: FakeProvider())
    site_settings.save({"featured_price": "33", "currency_code": "KES"})
    owner = make_user(is_landlord=True)
    billing.start_featured_checkout(owner, make_listing(owner, purpose="rent"))
    purchase = Purchase.objects.get()
    assert purchase.amount == Decimal("33") and purchase.currency == "KES"
    assert sent["request"].currency == "KES" and sent["request"].item.amount_cents == 3300


def test_currency_symbol_and_site_name_reach_templates(client):
    site_settings.save({"currency_symbol": "KSh ", "site_name": "Nyumba"})
    assert Template("{% load ui %}{{ v|money }}").render(Context({"v": 1500})) == "KSh 1,500"
    html = client.get(reverse("core:home")).content.decode()
    assert "<title>" in html and "Nyumba" in html


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------
def test_settings_page_staff_only(client, make_user):
    client.force_login(make_user(is_buyer=True))
    assert client.get(reverse("staff:settings")).status_code in (302, 403)


def test_settings_page_saves_and_audits(staff_client, staff):
    resp = staff_client.post(reverse("staff:settings"), _site_post(currency_code="ngn", currency_symbol="₦", featured_price="15000"))
    assert resp.status_code == 302
    assert site_settings.get("currency_code") == "NGN"
    assert site_settings.get("featured_price") == Decimal("15000")
    entry = AuditLog.objects.get(action="settings.update")
    assert entry.actor == staff
    assert entry.changes["currency_code"] == ["USD", "NGN"]


def test_settings_page_validates(staff_client):
    resp = staff_client.post(reverse("staff:settings"), _site_post(currency_code="DOLLARS", featured_days="0"))
    assert resp.status_code == 200
    assert site_settings.get("currency_code") == "USD"
    assert not AuditLog.objects.exists()


def test_logo_upload_and_reset(staff_client):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "green").save(buf, "PNG")
    staff_client.post(reverse("staff:settings"), _site_post(logo=SimpleUploadedFile("logo.png", buf.getvalue(), "image/png")))
    assert site_settings.get("logo").startswith("brand/logo-")
    assert "/media/brand/logo-" in site_settings.logo_url()
    staff_client.post(reverse("staff:settings"), _site_post(clear_logo="on"))
    assert site_settings.get("logo") == ""
    assert site_settings.logo_url().endswith(".svg")


def test_plans_are_editable(staff_client):
    plans = list(Plan.objects.order_by("sort_order", "price_monthly"))
    data = {"section": "plans", "plans-TOTAL_FORMS": len(plans), "plans-INITIAL_FORMS": len(plans),
            "plans-MIN_NUM_FORMS": 0, "plans-MAX_NUM_FORMS": 1000}
    for i, p in enumerate(plans):
        data.update({f"plans-{i}-id": p.pk, f"plans-{i}-name": p.name, f"plans-{i}-price_monthly": p.price_monthly,
                     f"plans-{i}-listing_limit": p.listing_limit, f"plans-{i}-seats": p.seats,
                     f"plans-{i}-description": p.description, f"plans-{i}-is_active": "on"})
    data["plans-0-price_monthly"] = "35.00"
    assert staff_client.post(reverse("staff:settings"), data).status_code == 302
    plans[0].refresh_from_db()
    assert plans[0].price_monthly == Decimal("35.00")
    entry = AuditLog.objects.get(action="plan.update")
    assert "price_monthly" in entry.changes


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def test_moderation_and_user_actions_are_audited(staff_client, make_user, make_listing):
    owner = make_user(is_seller=True)
    listing = make_listing(owner, status=ListingStatus.PENDING)
    staff_client.post(reverse("staff:moderation_action", args=[listing.pk]), {"decision": "reject", "note": "Blurry photos"})
    staff_client.post(reverse("staff:user_action", args=[owner.pk, "suspend"]))
    staff_client.post(reverse("staff:user_action", args=[owner.pk, "roles"]), {"roles": ["seller", "landlord"]})
    actions = list(AuditLog.objects.order_by("created_at", "id").values_list("action", flat=True))
    assert actions == ["listing.reject", "user.suspend", "user.roles"]
    rejected = AuditLog.objects.get(action="listing.reject")
    assert rejected.note == "Blurry photos" and rejected.target_id == str(listing.pk)
    assert AuditLog.objects.get(action="user.roles").changes["roles"][1] == ["landlord", "seller"]


def test_bulk_delete_is_audited_per_listing(staff_client, make_user, make_listing):
    owner = make_user(is_seller=True)
    a, b = make_listing(owner, title="A"), make_listing(owner, title="B")
    staff_client.post(reverse("staff:listings_bulk"), {"action": "delete", "ids": [a.pk, b.pk], "confirm": "DELETE"})
    assert set(AuditLog.objects.filter(action="listing.delete").values_list("target_label", flat=True)) == {"A", "B"}


def test_audit_page_lists_and_filters(staff_client, staff):
    from apps.core import audit

    audit.record(None, "settings.update", changes={"site_name": ["A", "B"]}, actor=staff)
    audit.record(None, "user.suspend", staff, actor=staff, note="spam")
    resp = staff_client.get(reverse("staff:audit"))
    html = resp.content.decode()
    assert "Changed settings" in html and "Suspended user" in html
    resp = staff_client.get(reverse("staff:audit"), {"area": "settings"})
    assert [e.action for e in resp.context["table"].page.object_list] == ["settings.update"]
    resp = staff_client.get(reverse("staff:audit"), {"q": "spam"})
    assert [e.action for e in resp.context["table"].page.object_list] == ["user.suspend"]


# ---------------------------------------------------------------------------
# Email previews
# ---------------------------------------------------------------------------
def test_every_email_template_renders_in_preview(staff_client):
    for name in _sample_contexts():
        assert staff_client.get(reverse("staff:emails"), {"t": name}).status_code == 200
        resp = staff_client.get(reverse("staff:email_preview", args=[name]))
        assert resp.status_code == 200
        assert "sandbox" in resp["Content-Security-Policy"]


def test_emails_use_site_settings():
    from apps.core.emails import render_email

    site_settings.save({"site_name": "Nyumba"})
    subject, text, html = render_email("verify_email", {"user_name": "Kwame", "path": "/x/"})
    assert "Nyumba" in subject and "Nyumba" in html
