"""Signed, expiring tokens for email verification (no extra table needed)."""

from django.conf import settings
from django.core import signing

SALT = "accounts.email-verification"


def make_email_token(user):
    # Including the email means changing the address invalidates old links.
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=SALT)


def read_email_token(token):
    """Return (user_id, email) or None if invalid/expired."""
    try:
        data = signing.loads(token, salt=SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE)
    except signing.BadSignature:
        return None
    return data.get("uid"), data.get("email")
