"""
Search filters. One form parses the URL query string; the same code runs for
the search page, saved searches and the daily digest, so results always match.
"""

from decimal import Decimal

from django import forms
from django.contrib.gis.geos import Polygon
from django.http import QueryDict
from django.utils.translation import gettext_lazy as _

from apps.listings.forms import RESIDENTIAL_TYPES
from apps.listings.geo import within_polygon, within_radius
from apps.listings.models import Amenity, Listing, PropertyType, Purpose
from apps.core import site_settings

SORTS = [
    ("featured", _("Featured first")),
    ("newest", _("Newest")),
    ("price_asc", _("Price: low to high")),
    ("price_desc", _("Price: high to low")),
]
RADIUS_CHOICES = [("", _("Any distance")), ("2", _("Within 2 km")), ("5", _("Within 5 km")),
                  ("10", _("Within 10 km")), ("25", _("Within 25 km")), ("50", _("Within 50 km"))]
BED_CHOICES = [("", _("Any")), ("1", "1+"), ("2", "2+"), ("3", "3+"), ("4", "4+"), ("5", "5+")]
FURNISHED_CHOICES = [("", _("Any")), ("yes", _("Furnished")), ("no", _("Unfurnished"))]
MAX_AREA_POINTS = 60


def parse_points(text):
    """'lng,lat;lng,lat;...' -> [(lng, lat), ...] or None."""
    points = []
    for pair in (text or "").split(";"):
        try:
            lng, lat = (float(v) for v in pair.split(","))
        except ValueError:
            return None
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            return None
        points.append((lng, lat))
    return points


class SearchForm(forms.Form):
    purpose = forms.ChoiceField(label=_("Looking to"), required=False,
                                choices=[("", _("Buy or rent")), (Purpose.SALE, _("Buy")), (Purpose.RENT, _("Rent"))])
    city = forms.CharField(label=_("City"), required=False, max_length=100)
    neighborhood = forms.CharField(label=_("Neighborhood"), required=False, max_length=120)
    type = forms.MultipleChoiceField(label=_("Property type"), required=False, choices=RESIDENTIAL_TYPES,
                                     widget=forms.CheckboxSelectMultiple)
    price_min = forms.DecimalField(label=_("Min price"), required=False, min_value=0, max_digits=12, decimal_places=0)
    price_max = forms.DecimalField(label=_("Max price"), required=False, min_value=0, max_digits=12, decimal_places=0)
    beds = forms.ChoiceField(label=_("Bedrooms"), required=False, choices=BED_CHOICES)
    baths = forms.ChoiceField(label=_("Bathrooms"), required=False, choices=BED_CHOICES[:5])
    area_min = forms.IntegerField(label=_("Min area (m²)"), required=False, min_value=0)
    area_max = forms.IntegerField(label=_("Max area (m²)"), required=False, min_value=0)
    furnished = forms.ChoiceField(label=_("Furnished"), required=False, choices=FURNISHED_CHOICES)
    amenities = forms.MultipleChoiceField(label=_("Amenities"), required=False, widget=forms.CheckboxSelectMultiple)
    sort = forms.ChoiceField(label=_("Sort by"), required=False, choices=SORTS)
    # Location: radius around a point, and/or a drawn map area.
    near = forms.CharField(required=False, widget=forms.HiddenInput)      # "lat,lng"
    radius = forms.ChoiceField(label=_("Distance"), required=False, choices=RADIUS_CHOICES)
    area = forms.CharField(required=False, widget=forms.HiddenInput)      # "lng,lat;lng,lat;..."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amenities"].choices = list(Amenity.objects.values_list("slug", "name"))
        self.fields["type"].widget.attrs["class"] = "check"
        self.fields["amenities"].widget.attrs["class"] = "check"

    def clean_near(self):
        value = self.cleaned_data.get("near", "").strip()
        if not value:
            return None
        try:
            lat, lng = (float(v) for v in value.split(","))
        except ValueError:
            raise forms.ValidationError(_("Invalid location."))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise forms.ValidationError(_("Invalid location."))
        return (lat, lng)

    def clean_area(self):
        value = self.cleaned_data.get("area", "").strip()
        if not value:
            return None
        points = parse_points(value)
        if not points or not (3 <= len(points) <= MAX_AREA_POINTS):
            raise forms.ValidationError(_("Invalid map area."))
        try:
            ring = points + ([points[0]] if points[0] != points[-1] else [])
            if not Polygon(ring, srid=4326).valid:
                raise ValueError
        except Exception:
            raise forms.ValidationError(_("Invalid map area."))
        return points

    def clean(self):
        data = super().clean()
        lo, hi = data.get("price_min"), data.get("price_max")
        if lo is not None and hi is not None and lo > hi:
            data["price_min"], data["price_max"] = hi, lo
        lo, hi = data.get("area_min"), data.get("area_max")
        if lo is not None and hi is not None and lo > hi:
            data["area_min"], data["area_max"] = hi, lo
        return data


MORE_FILTER_FIELDS = ("area_min", "area_max", "neighborhood", "radius", "amenities")


def count_more_filters(data):
    """How many filters inside the 'More filters' panel are active (shown as a badge)."""
    return sum(1 for f in MORE_FILTER_FIELDS if data.get(f) not in (None, "", []))


def city_center(city):
    """Average pin position of a city's published listings, for radius search without a map."""
    points = list(
        Listing.objects.published().filter(city__iexact=city).values_list("location__point", flat=True)[:500]
    )
    points = [p for p in points if p is not None]
    if not points:
        return None
    return (sum(p.y for p in points) / len(points), sum(p.x for p in points) / len(points))


def apply_filters(data, queryset=None):
    """Filter published listings with cleaned SearchForm data. Returns (queryset, center)."""
    qs = queryset if queryset is not None else Listing.objects.published()
    if data.get("purpose"):
        qs = qs.filter(purpose=data["purpose"])
    if data.get("city"):
        qs = qs.filter(city__iexact=data["city"].strip())
    if data.get("neighborhood"):
        qs = qs.filter(neighborhood__icontains=data["neighborhood"].strip())
    if data.get("type"):
        qs = qs.filter(property_type__in=data["type"])
    if data.get("price_min") is not None:
        qs = qs.filter(price__gte=data["price_min"])
    if data.get("price_max") is not None:
        qs = qs.filter(price__lte=data["price_max"])
    if data.get("beds"):
        qs = qs.filter(bedrooms__gte=int(data["beds"]))
    if data.get("baths"):
        qs = qs.filter(bathrooms__gte=int(data["baths"]))
    if data.get("area_min") is not None:
        qs = qs.filter(area_sqm__gte=data["area_min"])
    if data.get("area_max") is not None:
        qs = qs.filter(area_sqm__lte=data["area_max"])
    if data.get("furnished") == "yes":
        qs = qs.filter(furnished=True)
    elif data.get("furnished") == "no":
        qs = qs.filter(furnished=False)
    for slug in data.get("amenities") or []:
        qs = qs.filter(amenities__slug=slug)
    if data.get("area"):
        qs = within_polygon(qs, data["area"])

    center = data.get("near") or (city_center(data["city"]) if data.get("city") else None)
    sort = data.get("sort") or "featured"
    if data.get("radius") and center:
        qs = within_radius(qs, center[0], center[1], km=int(data["radius"]))
        if sort == "featured":
            return qs.order_by("-is_featured", "distance"), center
    orderings = {
        "featured": ("-is_featured", "-published_at"),
        "newest": ("-published_at",),
        "price_asc": ("price", "-published_at"),
        "price_desc": ("-price", "-published_at"),
    }
    return qs.order_by(*orderings[sort]), center


def search(query, queryset=None):
    """Parse a QueryDict/str and return (form, queryset, center)."""
    if isinstance(query, str):
        query = QueryDict(query)
    form = SearchForm(query)
    form.is_valid()  # invalid fields are dropped, valid ones still apply
    data = {k: v for k, v in form.cleaned_data.items() if k not in form.errors}
    qs, center = apply_filters(data, queryset)
    return form, qs, center


def describe(form):
    """Human summary used as a saved-search name, e.g. 'Rent · Nairobi · 2+ beds · up to $2,000'."""
    from apps.core.templatetags.ui import money

    d = form.cleaned_data if hasattr(form, "cleaned_data") else {}
    parts = []
    purpose = d.get("purpose")
    parts.append(str(_("Rent")) if purpose == Purpose.RENT else str(_("Buy")) if purpose == Purpose.SALE else str(_("Homes")))
    if d.get("type"):
        parts.append(", ".join(str(PropertyType(t).label) for t in d["type"]))
    place = d.get("neighborhood") or ""
    if d.get("city"):
        place = f"{place}, {d['city']}" if place else d["city"]
    if place:
        parts.append(place.title() if place.islower() else place)
    if d.get("area"):
        parts.append(str(_("map area")))
    if d.get("beds"):
        parts.append(str(_("%(n)s+ beds") % {"n": d["beds"]}))
    if d.get("price_max") is not None:
        parts.append(str(_("up to %(p)s") % {"p": money(d["price_max"])}))
    elif d.get("price_min") is not None:
        parts.append(str(_("from %(p)s") % {"p": money(d["price_min"])}))
    if d.get("radius"):
        parts.append(str(_("within %(km)s km") % {"km": d["radius"]}))
    return " · ".join(parts)[:120]


def heading(form):
    """Page heading such as 'Properties for rent in Lagos'."""
    d = getattr(form, "cleaned_data", {}) or {}
    place = d.get("neighborhood") or ""
    if d.get("city"):
        city = d["city"].strip()
        city = city.title() if city.islower() else city
        place = f"{place.title()}, {city}" if place else city
    if not place and d.get("area"):
        place = str(_("the map area"))
    purpose = d.get("purpose")
    if purpose == Purpose.RENT:
        return str(_("Properties for rent in %(place)s") % {"place": place}) if place else str(_("Properties for rent"))
    if purpose == Purpose.SALE:
        return str(_("Properties for sale in %(place)s") % {"place": place}) if place else str(_("Properties for sale"))
    return str(_("Properties in %(place)s") % {"place": place}) if place else str(_("Properties across Africa"))


def clean_querystring(query):
    """Keep only known, non-empty filter params (drops page, csrf, etc.)."""
    if isinstance(query, str):
        query = QueryDict(query)
    out = QueryDict(mutable=True)
    for key in SearchForm.base_fields:
        values = [v for v in query.getlist(key) if v.strip()]
        if key == "sort" and values == ["featured"]:
            continue  # the default sort adds nothing
        if values:
            out.setlist(key, values)
    return out.urlencode()


def short_price(amount):
    """Compact price for map bubbles: $1.25M, $850K, $1,800."""
    from django.conf import settings

    amount = Decimal(amount)
    sym = site_settings.get("currency_symbol")
    if amount >= 1_000_000:
        return f"{sym}{(amount / 1_000_000).quantize(Decimal('0.01')).normalize():f}M"
    if amount >= 100_000:
        return f"{sym}{int(amount / 1000)}K"
    return f"{sym}{int(amount):,}"


def map_point(listing):
    loc = getattr(listing, "location", None)
    if not loc:
        return None
    cover = listing.cover
    return {
        "id": listing.pk,
        "lat": round(loc.latitude, 6),
        "lng": round(loc.longitude, 6),
        "price": short_price(listing.price),
        "title": listing.title,
        "url": listing.get_absolute_url(),
        "photo": cover.image.url if cover else "",
        "beds": listing.bedrooms,
        "baths": listing.bathrooms,
        "featured": listing.is_featured,
        "rent": listing.purpose == Purpose.RENT,
    }

