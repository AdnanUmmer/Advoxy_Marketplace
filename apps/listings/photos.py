"""Photo upload handling: validate, orient, downscale, strip metadata."""

import uuid
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import ListingPhoto
from .rules import MAX_PHOTOS

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def normalize_image(uploaded):
    """Return a ContentFile with a clean JPEG.

    Re-encoding drops EXIF data, including GPS coordinates that phones embed.
    """
    max_bytes = settings.LISTING_PHOTO_MAX_MB * 1024 * 1024
    if uploaded.size > max_bytes:
        raise ValidationError(_("%(name)s is larger than %(mb)s MB.") % {"name": uploaded.name, "mb": settings.LISTING_PHOTO_MAX_MB})
    try:
        img = Image.open(uploaded)
        fmt = img.format
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ValidationError(_("%(name)s is not a supported image.") % {"name": uploaded.name})
    if fmt not in ALLOWED_FORMATS:
        raise ValidationError(_("Upload JPEG, PNG or WebP photos."))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
    img.thumbnail((settings.LISTING_PHOTO_MAX_EDGE, settings.LISTING_PHOTO_MAX_EDGE), Image.LANCZOS)
    buf = BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85, optimize=True, progressive=True)
    return ContentFile(buf.getvalue(), name=f"{uuid.uuid4().hex}.jpg")


@transaction.atomic
def add_photos(listing, files):
    """Validate every file first, then save them all. Returns (saved, errors)."""
    existing = listing.photos.count()
    if existing + len(files) > MAX_PHOTOS:
        return [], [_("A listing can have up to %(n)s photos.") % {"n": MAX_PHOTOS}]
    processed, errors = [], []
    for f in files:
        try:
            processed.append(normalize_image(f))
        except ValidationError as exc:
            errors.extend(exc.messages)
    if errors:
        return [], errors
    start = (listing.photos.aggregate(m=Max("position"))["m"] or -1) + 1
    saved = []
    for offset, content in enumerate(processed):
        photo = ListingPhoto(listing=listing, position=start + offset, alt_text=listing.title)
        photo.image.save(content.name, content, save=False)
        photo.save()
        saved.append(photo)
    return saved, []


@transaction.atomic
def reorder(listing, ordered_ids):
    """Apply a new order. Unknown ids are ignored; missing ones keep their relative order at the end."""
    photos = {p.pk: p for p in listing.photos.select_for_update()}
    order = [int(i) for i in ordered_ids if str(i).isdigit() and int(i) in photos]
    order += [pk for pk in sorted(photos, key=lambda k: photos[k].position) if pk not in order]
    for position, pk in enumerate(order):
        if photos[pk].position != position:
            photos[pk].position = position
            photos[pk].save(update_fields=["position"])


def move(listing, photo_id, delta):
    ids = list(listing.photos.values_list("pk", flat=True))
    if photo_id not in ids:
        return
    i = ids.index(photo_id)
    j = max(0, min(len(ids) - 1, i + delta))
    ids[i], ids[j] = ids[j], ids[i]
    reorder(listing, ids)


def make_cover(listing, photo_id):
    ids = list(listing.photos.values_list("pk", flat=True))
    if photo_id in ids:
        ids.remove(photo_id)
        reorder(listing, [photo_id] + ids)


def delete_photo(listing, photo_id):
    photo = listing.photos.filter(pk=photo_id).first()
    if photo:
        storage, name = photo.image.storage, photo.image.name
        photo.delete()
        # Seed photos are shared between listings; only delete files we own.
        if not name.startswith("seed/") and not ListingPhoto.objects.filter(image=name).exists():
            transaction.on_commit(lambda: storage.delete(name))
        reorder(listing, [])
