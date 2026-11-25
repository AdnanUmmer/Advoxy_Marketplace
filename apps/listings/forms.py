from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .geo import make_point
from .models import Amenity, Listing, ListingLocation, PropertyType, Purpose

# Phase 1 is residential only (SPEC section 15). Land and commercial stay in the data model.
RESIDENTIAL_TYPES = [(t.value, t.label) for t in (PropertyType.APARTMENT, PropertyType.VILLA, PropertyType.TOWNHOUSE)]


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    """Accepts several files; each is validated in photos.normalize_image."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleImageField, self).clean(f, initial) for f in files]


class ListingForm(forms.ModelForm):
    purpose = forms.ChoiceField(label=_("Purpose"), choices=Purpose.choices, widget=forms.RadioSelect, initial=Purpose.SALE)
    property_type = forms.ChoiceField(label=_("Property type"), choices=RESIDENTIAL_TYPES)
    amenities = forms.ModelMultipleChoiceField(
        label=_("Amenities"), queryset=Amenity.objects.all(), required=False, widget=forms.CheckboxSelectMultiple
    )
    latitude = forms.DecimalField(label=_("Latitude"), max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    longitude = forms.DecimalField(label=_("Longitude"), max_digits=9, decimal_places=6, min_value=-180, max_value=180)
    photos = MultipleImageField(label=_("Photos"), required=False,
                                help_text=_("JPEG, PNG or WebP, up to 10 MB each. The first photo is the cover."))

    class Meta:
        model = Listing
        fields = [
            "title", "purpose", "property_type", "price", "description",
            "bedrooms", "bathrooms", "area_sqm", "furnished", "amenities",
            "address", "neighborhood", "city", "country",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 7}),
            "price": forms.NumberInput(attrs={"min": "1", "step": "1", "inputmode": "numeric"}),
        }
        help_texts = {
            "price": _("For rentals, the monthly rent."),
            "address": _("Shown on the listing. Leave blank to show only the neighborhood."),
        }

    def __init__(self, *args, currency_code="USD", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["price"].label = _("Price (%(currency)s)") % {"currency": currency_code}
        self.fields["furnished"].widget.attrs["class"] = "check"
        self.fields["amenities"].widget.attrs["class"] = "check"
        self.fields["purpose"].widget.attrs["class"] = "accent-[var(--brand-primary)]"
        self.fields["title"].widget.attrs.update({"maxlength": 140, "placeholder": _("e.g. Bright 2-bed apartment near Karura Forest")})
        location = getattr(self.instance, "location", None) if self.instance.pk else None
        if location:
            self.initial.setdefault("latitude", round(Decimal(location.latitude), 6))
            self.initial.setdefault("longitude", round(Decimal(location.longitude), 6))
        if self.instance.pk:
            # Photos are managed on the edit page with the photo manager.
            del self.fields["photos"]

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price is None or price <= 0:
            raise forms.ValidationError(_("Enter a price above zero."))
        return price

    def clean_title(self):
        return " ".join(self.cleaned_data["title"].split())

    def save_location(self, listing):
        point = make_point(self.cleaned_data["latitude"], self.cleaned_data["longitude"])
        ListingLocation.objects.update_or_create(listing=listing, defaults={"point": point})
