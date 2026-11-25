from django.shortcuts import get_object_or_404, redirect, render

from .models import Listing, ListingStatus, Purpose


def search(request):
    """Milestone 1 stub: a plain grid filtered by city and purpose.
    Milestone 3 replaces this with full filters and the Mapbox split view."""
    qs = Listing.objects.published().prefetch_related("photos").order_by("-is_featured", "-published_at")
    city = request.GET.get("city", "").strip()
    purpose = request.GET.get("purpose", "")
    if city:
        qs = qs.filter(city__iexact=city)
    if purpose in Purpose.values:
        qs = qs.filter(purpose=purpose)
    return render(request, "listings/search.html", {"listings": qs[:48], "city": city, "purpose": purpose, "total": qs.count()})


def detail(request, pk, slug):
    """Milestone 1 stub. The full detail page (gallery, map, inquiry form) is milestone 2."""
    listing = get_object_or_404(
        Listing.objects.select_related("owner", "location").prefetch_related("photos", "amenities"), pk=pk
    )
    if listing.status != ListingStatus.PUBLISHED and listing.owner_id != request.user.pk and not request.user.is_staff:
        return render(request, "404.html", status=404)
    if slug != listing.slug:
        return redirect(listing, permanent=True)
    return render(request, "listings/detail.html", {"listing": listing})
