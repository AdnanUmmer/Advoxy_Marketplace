from django.conf import settings
from django.utils.functional import SimpleLazyObject

from config.brand import BRAND


def _favorite_ids(user):
    if not user.is_authenticated:
        return frozenset()
    from apps.search.models import Favorite

    return frozenset(Favorite.objects.filter(user=user).values_list("listing_id", flat=True))


def site(request):
    user = getattr(request, "user", None)
    return {
        "brand": BRAND,
        "DEMO_MODE": settings.DEMO_MODE,
        "CURRENCY_CODE": settings.CURRENCY_CODE,
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
        "GOOGLE_SIGNIN": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        # Evaluated only when a template asks (listing cards' heart buttons).
        "favorite_ids": SimpleLazyObject(lambda: _favorite_ids(user)) if user else frozenset(),
    }
