from django.contrib.gis import admin

from .models import Amenity, Listing, ListingLocation, ListingPhoto


class PhotoInline(admin.TabularInline):
    model = ListingPhoto
    extra = 0


class LocationInline(admin.StackedInline):
    model = ListingLocation


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ["title", "city", "purpose", "property_type", "price", "status", "is_featured"]
    list_filter = ["status", "purpose", "property_type", "country", "is_featured"]
    search_fields = ["title", "city", "neighborhood"]
    inlines = [LocationInline, PhotoInline]


admin.site.register(Amenity)
