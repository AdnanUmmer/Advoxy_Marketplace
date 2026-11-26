"""Admin-editable site settings.

Every setting has a typed default here (from env/brand config), and staff can override it
on /staff/settings/ without touching code. Read with `site_settings.get("featured_price")`.
Values are cached; saving through `save()` clears the cache.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from config.brand import BRAND

CACHE_KEY = "site_settings:v1"
CACHE_SECONDS = 300


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str          # text | int | money | file
    default: object
    help: str = ""
    group: str = "general"
    min_value: int = 0
    max_value: int = 100_000


def _fields():
    return [
        Field("site_name", _("Site name"), "text", BRAND["name"], _("Shown in the header, page titles and emails."), "brand"),
        Field("logo", _("Logo mark"), "file", "", _("Square image, at least 128 px. Leave empty to use the default."), "brand"),
        Field("support_email", _("Support email"), "text", BRAND["support_email"], _("Shown in the footer and emails."), "brand"),
        Field("currency_code", _("Currency code"), "text", settings.CURRENCY_CODE,
              _("Three-letter ISO code used for prices and Stripe payments, e.g. USD."), "money"),
        Field("currency_symbol", _("Currency symbol"), "text", settings.CURRENCY_SYMBOL, _("Shown before prices, e.g. $."), "money"),
        Field("featured_price", _("Featured placement price"), "money", Decimal(settings.FEATURED_PRICE), "", "money", 1, 10_000_000),
        Field("featured_days", _("Featured placement length (days)"), "int", settings.FEATURED_DAYS, "", "money", 1, 365),
        Field("extra_listing_price", _("Extra listing slot price"), "money", Decimal(settings.EXTRA_LISTING_PRICE), "", "money", 1, 10_000_000),
        Field("extra_listing_days", _("Extra listing slot length (days)"), "int", settings.EXTRA_LISTING_DAYS, "", "money", 1, 365),
        Field("free_seller_listings", _("Free listings for sellers"), "int", 1,
              _("Active listings an individual seller gets without paying."), "limits", 0, 50),
        Field("free_landlord_listings", _("Free listings for landlords"), "int", 2,
              _("Active listings an individual landlord gets without paying."), "limits", 0, 50),
        Field("listing_lifetime_days", _("Listing lifetime (days)"), "int", getattr(settings, "LISTING_LIFETIME_DAYS", 90),
              _("Published listings expire after this many days unless renewed."), "limits", 7, 730),
    ]


FIELDS = {f.key: f for f in _fields()}
GROUPS = [("brand", _("Brand")), ("money", _("Currency and prices")), ("limits", _("Listing limits"))]


def coerce(field, raw):
    if raw in (None, ""):
        return field.default if field.kind != "file" else ""
    if field.kind == "int":
        return int(raw)
    if field.kind == "money":
        return Decimal(str(raw))
    return str(raw)


def all_values():
    values = cache.get(CACHE_KEY)
    if values is None:
        from .models import Setting

        stored = dict(Setting.objects.values_list("key", "value"))
        values = {key: coerce(f, stored.get(key)) for key, f in FIELDS.items()}
        cache.set(CACHE_KEY, values, CACHE_SECONDS)
    return values


def get(key):
    return all_values()[key]


def save(changes, user=None):
    """Store changed values. Returns {key: (old, new)} for the audit log."""
    from .models import Setting

    current = all_values()
    diff = {}
    for key, value in changes.items():
        field = FIELDS[key]
        new = coerce(field, value)
        if new != current[key]:
            stored = str(new) if isinstance(new, Decimal) else new
            Setting.objects.update_or_create(key=key, defaults={"value": stored, "updated_by": user})
            diff[key] = (_plain(current[key]), _plain(new))
    clear_cache()
    return diff


def clear_cache():
    cache.delete(CACHE_KEY)


def _plain(value):
    return str(value) if isinstance(value, Decimal) else value


def logo_url():
    from django.core.files.storage import default_storage
    from django.templatetags.static import static

    path = get("logo")
    return default_storage.url(path) if path else static(BRAND["logo_mark"])


def brand():
    """BRAND config with admin overrides applied, for templates and emails."""
    return {**BRAND, "name": get("site_name"), "support_email": get("support_email"), "mark_url": logo_url()}
