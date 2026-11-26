from django.core.management.base import BaseCommand

from apps.listings.models import ListingPhoto


class Command(BaseCommand):
    help = "Create missing listing photo thumbnails (safe to run repeatedly; deploy.sh runs it)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Rebuild every thumbnail, not only missing ones.")

    def handle(self, *args, **opts):
        qs = ListingPhoto.objects.all() if opts["all"] else ListingPhoto.objects.filter(thumbnail="")
        made = failed = 0
        for photo in qs.iterator():
            if opts["all"] and photo.thumbnail:
                photo.thumbnail.delete(save=False)
            if photo.make_thumbnail():
                ListingPhoto.objects.filter(pk=photo.pk).update(thumbnail=photo.thumbnail.name)
                made += 1
            else:
                failed += 1
        self.stdout.write(self.style.SUCCESS(f"Thumbnails created: {made}. Unreadable images: {failed}."))
