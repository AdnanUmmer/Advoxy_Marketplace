from django.shortcuts import render

from apps.listings.markets import country_priority, popular_cities
from apps.listings.models import Listing
from apps.search.filters import SearchForm


def home(request):
    published = Listing.objects.published()
    featured = (
        published.filter(is_featured=True)
        .select_related("location")
        .prefetch_related("photos")
        .annotate(rank=country_priority())
        .order_by("rank", "-published_at")[:8]
    )
    areas = popular_cities(limit=12)
    default_purpose = "rent" if request.user.is_authenticated and request.user.primary_role == "renter" else "sale"
    form = SearchForm(initial={"purpose": default_purpose})
    return render(request, "core/home.html", {"featured": featured, "areas": areas, "default_purpose": default_purpose, "form": form})


def about(request):
    return render(request, "core/about.html")


def contact(request):
    return render(request, "core/contact.html")


def help_page(request):
    return render(request, "core/help.html")


def styleguide(request):
    """Design-system reference page. Only routed when DEBUG is on."""
    return render(request, "core/styleguide.html")


def healthz(request):
    """Liveness check for deploy.sh and uptime monitors: database and cache reachable."""
    from django.core.cache import cache
    from django.db import connection
    from django.http import JsonResponse

    status = {"db": False, "cache": False}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        status["db"] = True
        cache.set("healthz", 1, 10)
        status["cache"] = cache.get("healthz") == 1
    except Exception:  # noqa: BLE001 (report, don't crash)
        pass
    ok = all(status.values())
    response = JsonResponse({"ok": ok, **status}, status=200 if ok else 503)
    response["Cache-Control"] = "no-store"
    return response

