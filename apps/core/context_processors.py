from django.conf import settings

from config.brand import BRAND


def site(request):
    return {
        "brand": BRAND,
        "DEMO_MODE": settings.DEMO_MODE,
        "CURRENCY_CODE": settings.CURRENCY_CODE,
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
    }
