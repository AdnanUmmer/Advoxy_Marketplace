from django.conf import settings

from .base import PaymentError, PaymentProvider, WebhookVerificationError  # noqa: F401


def get_provider(name=None) -> PaymentProvider:
    """The configured payment provider (settings.PAYMENT_PROVIDER)."""
    name = name or settings.PAYMENT_PROVIDER
    if name == "stripe":
        from .stripe_provider import StripeProvider

        return StripeProvider()
    raise ValueError(f"Unknown payment provider: {name}")
