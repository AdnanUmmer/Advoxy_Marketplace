from django.db.models import Count
from django.shortcuts import render

from apps.listings.models import Listing


def home(request):
    published = Listing.objects.published()
    featured = (
        published.filter(is_featured=True).select_related("location").prefetch_related("photos").order_by("-published_at")[:6]
    )
    areas = (
        published.values("city", "country").annotate(total=Count("id")).order_by("-total", "city")[:8]
    )
    default_purpose = "rent" if request.user.is_authenticated and request.user.primary_role == "renter" else "sale"
    return render(request, "core/home.html", {"featured": featured, "areas": areas, "default_purpose": default_purpose})


def about(request):
    return render(request, "core/about.html")


def contact(request):
    return render(request, "core/contact.html")


def help_page(request):
    return render(request, "core/help.html")


def styleguide(request):
    """Design-system reference page. Only routed when DEBUG is on."""
    return render(request, "core/styleguide.html")
