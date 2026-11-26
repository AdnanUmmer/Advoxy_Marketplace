"""Payment adapter interface (SPEC section 8).

The rest of the app talks only to this interface, so a second provider
(for example Flutterwave or Paystack for countries Stripe doesn't cover)
can be added as another subclass without touching views or services.
"""

from dataclasses import dataclass, field


class PaymentError(Exception):
    """A provider call failed (network, configuration, rejected request)."""


class WebhookVerificationError(Exception):
    """The webhook body or signature could not be verified."""


@dataclass
class LineItem:
    name: str
    amount_cents: int
    description: str = ""


@dataclass
class CheckoutRequest:
    mode: str                      # "payment" (one-time) or "subscription"
    item: LineItem
    customer_email: str
    success_url: str               # provider appends its own session placeholder if needed
    cancel_url: str
    reference: str                 # our id, echoed back (client_reference_id)
    metadata: dict = field(default_factory=dict)
    currency: str = "usd"
    interval: str = "month"        # subscriptions only


@dataclass
class CheckoutResult:
    session_id: str
    url: str


@dataclass
class NormalizedEvent:
    """Provider event mapped to the shapes services understand."""

    id: str
    type: str   # checkout.completed | subscription.updated | subscription.deleted | invoice.paid | payment.refunded | ignored
    data: dict


class PaymentProvider:
    name = "base"

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        raise NotImplementedError

    def handle_webhook(self, payload: bytes, signature: str) -> NormalizedEvent:
        """Verify the signature and return a normalized event. Raises WebhookVerificationError."""
        raise NotImplementedError

    def cancel_subscription(self, provider_subscription_id: str, at_period_end: bool = True) -> dict:
        raise NotImplementedError

    def fetch_checkout(self, session_id: str) -> NormalizedEvent | None:
        """Look up a finished checkout (used on the success page as a fallback to webhooks)."""
        raise NotImplementedError

    def dashboard_url(self, kind: str, provider_id: str) -> str:
        return ""
