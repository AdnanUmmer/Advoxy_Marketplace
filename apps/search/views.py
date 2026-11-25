from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.permissions import verified_email_required
from apps.listings.models import Listing, Purpose
from apps.listings.views import mapbox_token

from . import filters
from .models import Favorite, SavedSearch

PAGE_SIZE = 24
MAP_LIMIT = 500


def results(request):
    query = request.GET.copy()
    # Renters land on rentals by default (QUESTIONS.md Q3).
    if "purpose" not in query and request.user.is_authenticated and request.user.primary_role == "renter":
        query["purpose"] = Purpose.RENT
    form, qs, center = filters.search(query)
    qs = qs.select_related("location").prefetch_related("photos")
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    pins = [p for p in (filters.map_point(l) for l in qs[:MAP_LIMIT]) if p]
    clean_qs = filters.clean_querystring(query)
    context = {
        "form": form,
        "page": page,
        "total": page.paginator.count,
        "pins": pins,
        "center": center,
        "querystring": clean_qs,
        "summary": filters.describe(form),
        "active_more": filters.count_more_filters(form.cleaned_data),
        "cities": Listing.objects.published().order_by("city").values_list("city", flat=True).distinct(),
        "mapbox_token": mapbox_token(),
        "already_saved": request.user.is_authenticated
        and SavedSearch.objects.filter(user=request.user, query=clean_qs).exists(),
    }
    if request.htmx and not request.htmx.boosted:
        response = render(request, "search/_results.html", context)
        # Keep the address bar clean and shareable (no empty parameters).
        page_param = f"page={page.number}" if page.number > 1 else ""
        qs_parts = "&".join(p for p in (clean_qs, page_param) if p)
        response["HX-Push-Url"] = reverse("search:results") + (f"?{qs_parts}" if qs_parts else "")
        return response
    return render(request, "search/results.html", context)


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------
@require_POST
@verified_email_required
def favorite_toggle(request, pk):
    listing = get_object_or_404(Listing.objects.published(), pk=pk)
    fav, created = Favorite.objects.get_or_create(user=request.user, listing=listing)
    if not created:
        fav.delete()
    if request.htmx:
        return render(request, "search/_favorite_button.html", {"listing": listing, "is_favorite": created})
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else listing.get_absolute_url())


@login_required
def favorites(request):
    favs = (
        Favorite.objects.filter(user=request.user, listing__status="published")
        .select_related("listing")
        .prefetch_related("listing__photos")
    )
    return render(request, "search/favorites.html", {"listings": [f.listing for f in favs]})


# ---------------------------------------------------------------------------
# Saved searches
# ---------------------------------------------------------------------------
@require_POST
@verified_email_required
def saved_search_create(request):
    query = filters.clean_querystring(request.POST.get("query", ""))
    form, _qs, _c = filters.search(query)
    name = (request.POST.get("name") or "").strip()[:120] or filters.describe(form)
    obj, created = SavedSearch.objects.get_or_create(user=request.user, query=query, defaults={"name": name})
    if created:
        messages.success(request, _("Search saved. We'll email you once a day when new homes match."))
    else:
        messages.info(request, _("You already saved this search."))
    return redirect(reverse("search:results") + (f"?{query}" if query else ""))


@login_required
def saved_searches(request):
    items = SavedSearch.objects.filter(user=request.user)
    return render(request, "search/saved_searches.html", {"items": items})


@require_POST
@login_required
def saved_search_update(request, pk, op):
    item = get_object_or_404(SavedSearch, pk=pk, user=request.user)
    if op == "delete":
        item.delete()
        if request.htmx:
            return HttpResponse("")
        messages.success(request, _("Saved search deleted."))
    elif op == "alerts":
        item.email_alerts = not item.email_alerts
        item.save(update_fields=["email_alerts"])
        if request.htmx:
            return render(request, "search/_saved_search_row.html", {"item": item})
    return redirect("search:saved")
