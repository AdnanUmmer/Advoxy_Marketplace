from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class PropertyType(models.TextChoices):
    APARTMENT = "apartment", _("Apartment")
    VILLA = "villa", _("Villa")
    TOWNHOUSE = "townhouse", _("Townhouse")
    # In the data model for later phases; phase 1 uses the residential form.
    LAND = "land", _("Land")
    COMMERCIAL = "commercial", _("Commercial")


class Purpose(models.TextChoices):
    SALE = "sale", _("For sale")
    RENT = "rent", _("For rent")


class ListingStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PENDING = "pending", _("Pending review")
    PUBLISHED = "published", _("Published")
    EXPIRED = "expired", _("Expired")
    SOLD = "sold", _("Sold")
    RENTED = "rented", _("Rented")
    REMOVED = "removed", _("Removed")


class Amenity(models.Model):
    name = models.CharField(_("name"), max_length=80, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = _("amenities")

    def __str__(self):
        return self.name


class ListingQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=ListingStatus.PUBLISHED)


class Listing(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings")
    agency = models.ForeignKey(
        "accounts.AgencyTeam", on_delete=models.SET_NULL, null=True, blank=True, related_name="listings"
    )
    title = models.CharField(_("title"), max_length=140)
    slug = models.SlugField(max_length=160)
    description = models.TextField(_("description"))
    property_type = models.CharField(_("type"), max_length=12, choices=PropertyType.choices)
    purpose = models.CharField(_("purpose"), max_length=4, choices=Purpose.choices)
    price = models.DecimalField(_("price"), max_digits=12, decimal_places=2)
    bedrooms = models.PositiveSmallIntegerField(_("bedrooms"), default=0)
    bathrooms = models.PositiveSmallIntegerField(_("bathrooms"), default=0)
    area_sqm = models.PositiveIntegerField(_("area (m²)"), null=True, blank=True)
    furnished = models.BooleanField(_("furnished"), default=False)
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="listings", verbose_name=_("amenities"))
    address = models.CharField(_("address"), max_length=255, blank=True)
    city = models.CharField(_("city"), max_length=100, db_index=True)
    country = models.CharField(_("country"), max_length=100, db_index=True)
    neighborhood = models.CharField(_("neighborhood"), max_length=120, blank=True, db_index=True)
    status = models.CharField(_("status"), max_length=10, choices=ListingStatus.choices, default=ListingStatus.DRAFT)
    is_featured = models.BooleanField(_("featured"), default=False)
    moderation_note = models.TextField(_("moderation note"), blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ListingQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "purpose", "property_type"]),
            models.Index(fields=["status", "-published_at"]),
            models.Index(fields=["price"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:150] or "listing"
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("listings:detail", args=[self.pk, self.slug])

    @property
    def cover(self):
        photos = list(self.photos.all())  # uses prefetch when available
        return photos[0] if photos else None


class ListingLocation(models.Model):
    """Map pin. Stored as a PostGIS geography point so distances are in metres."""

    listing = models.OneToOneField(Listing, on_delete=models.CASCADE, related_name="location")
    point = gis_models.PointField(geography=True, srid=4326, spatial_index=True)

    def __str__(self):
        return f"{self.listing_id}: {self.point.y:.5f}, {self.point.x:.5f}"

    @property
    def latitude(self):
        return self.point.y

    @property
    def longitude(self):
        return self.point.x


class ListingPhoto(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(_("photo"), upload_to="listings/%Y/%m/")
    # Smaller copy for cards, rows and tables (performance pass, milestone 8). Made on save.
    thumbnail = models.ImageField(upload_to="listings/thumbs/%Y/%m/", blank=True, editable=False)
    alt_text = models.CharField(_("description for screen readers"), max_length=200, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    THUMB_EDGE = 800

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"Photo {self.position} of {self.listing_id}"

    @property
    def thumb_url(self):
        return self.thumbnail.url if self.thumbnail else self.image.url

    def make_thumbnail(self):
        """Create the thumbnail from the main image. Returns False if the image can't be read."""
        from io import BytesIO
        from pathlib import PurePath

        from django.core.files.base import ContentFile
        from PIL import Image, UnidentifiedImageError

        try:
            self.image.open("rb")
            with Image.open(self.image) as img:
                img = img.convert("RGB")
                img.thumbnail((self.THUMB_EDGE, self.THUMB_EDGE), Image.LANCZOS)
                buf = BytesIO()
                img.save(buf, "JPEG", quality=78, optimize=True, progressive=True)
        except (FileNotFoundError, UnidentifiedImageError, OSError, ValueError):
            return False
        finally:
            try:
                self.image.close()
            except Exception:  # noqa: BLE001 (closing a missing file)
                pass
        self.thumbnail.save(f"{PurePath(self.image.name).stem}.jpg", ContentFile(buf.getvalue()), save=False)
        return True

    def save(self, *args, **kwargs):
        if self.image and not self.thumbnail:
            self.make_thumbnail()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        thumb = self.thumbnail.name if self.thumbnail else None
        result = super().delete(*args, **kwargs)
        # Demo photos share thumbnails; remove the file only when nothing else uses it.
        if thumb and not ListingPhoto.objects.filter(thumbnail=thumb).exists():
            from django.db import transaction

            storage = self.thumbnail.storage
            transaction.on_commit(lambda: storage.delete(thumb))
        return result
