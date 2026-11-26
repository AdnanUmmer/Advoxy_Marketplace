"""Sign in with Google (OpenID Connect, authorization code flow with PKCE).

Flow: /accounts/google/ -> Google consent -> /accounts/google/callback/
  * known Google account            -> signed in
  * existing account with the email -> linked, then signed in
  * new person                      -> /accounts/google/finish/ to pick roles and accept the terms

The ID token comes straight from Google's token endpoint over TLS in exchange for a
one-time code and our client secret, so per OpenID Connect Core 3.1.3.7 its claims are
validated (issuer, audience, expiry, nonce) without fetching Google's signing keys.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core import site_settings

from .forms import ROLE_HELP
from .models import SIGNUP_ROLES, AgencyTeam, AgentProfile, Profile, Role, SocialAccount, User

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
BACKEND = "apps.accounts.backends.EmailBackend"
FLOW_KEY = "google_oauth"
PENDING_KEY = "google_pending"
PENDING_TTL = 15 * 60


class GoogleError(Exception):
    pass


def is_enabled():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _callback_url(request):
    return request.build_absolute_uri(reverse("accounts:google_callback"))


def _safe_next(request, value):
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return value
    return ""


# ---------------------------------------------------------------------------
# Talking to Google (patched in tests)
# ---------------------------------------------------------------------------
def exchange_code(code, redirect_uri, verifier):
    """Swap the one-time code for tokens. Returns the token response as a dict."""
    body = urllib.parse.urlencode({
        "code": code, "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (fixed https URL)
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise GoogleError("token exchange failed") from exc


def claims_from(token_response, nonce):
    """Decode and validate the ID token's claims."""
    try:
        payload = token_response["id_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (KeyError, IndexError, ValueError) as exc:
        raise GoogleError("malformed id token") from exc
    if claims.get("iss") not in ISSUERS:
        raise GoogleError("bad issuer")
    aud = claims.get("aud")
    if aud != settings.GOOGLE_CLIENT_ID and not (isinstance(aud, list) and settings.GOOGLE_CLIENT_ID in aud):
        raise GoogleError("bad audience")
    if int(claims.get("exp", 0)) < time.time():
        raise GoogleError("expired")
    if not nonce or not constant_time_compare(str(claims.get("nonce", "")), nonce):
        raise GoogleError("bad nonce")
    if not claims.get("sub") or not claims.get("email") or claims.get("email_verified") not in (True, "true"):
        raise GoogleError("email not verified")
    return claims


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def start(request):
    if not is_enabled():
        raise Http404
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    request.session[FLOW_KEY] = {"state": state, "nonce": nonce, "verifier": verifier,
                                 "next": _safe_next(request, request.GET.get("next", ""))}
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID, "redirect_uri": _callback_url(request), "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
    }
    return redirect(f"{AUTH_URL}?{urllib.parse.urlencode(params)}")


def _fail(request, text=None):
    messages.error(request, text or _("Google sign-in didn't work. Please try again or use your email and password."))
    return redirect("accounts:login")


def _sign_in(request, user, next_url):
    login(request, user, backend=BACKEND)
    return redirect(next_url or settings.LOGIN_REDIRECT_URL)


def callback(request):
    if not is_enabled():
        raise Http404
    flow = request.session.pop(FLOW_KEY, None)
    if not flow or not constant_time_compare(request.GET.get("state", ""), flow["state"]):
        return _fail(request)
    if request.GET.get("error") or not request.GET.get("code"):
        return _fail(request, _("Google sign-in was cancelled."))
    try:
        claims = claims_from(exchange_code(request.GET["code"], _callback_url(request), flow["verifier"]), flow["nonce"])
    except GoogleError:
        return _fail(request)

    sub, email = str(claims["sub"]), claims["email"].strip().lower()
    link = SocialAccount.objects.select_related("user").filter(provider=SocialAccount.GOOGLE, uid=sub).first()
    user = link.user if link else User.objects.filter(email__iexact=email).first()
    if user is not None:
        if user.is_staff:
            return _fail(request, _("Staff accounts sign in with email and password."))
        if not user.is_active or user.is_suspended:
            return _fail(request, _("This account is not active."))
        if request.user.is_authenticated and request.user.pk != user.pk:
            return _fail(request, _("That Google account belongs to a different user."))
        with transaction.atomic():
            if link is None:
                SocialAccount.objects.create(user=user, provider=SocialAccount.GOOGLE, uid=sub, email=email)
            else:
                SocialAccount.objects.filter(pk=link.pk).update(email=email, last_login_at=timezone.now())
            if not user.is_email_verified:
                # Google proved the person owns this address. Someone else may have registered it
                # with a password they know, so that password stops working.
                user.email_verified_at = timezone.now()
                user.set_unusable_password()
                user.save(update_fields=["email_verified_at", "password"])
        return _sign_in(request, user, flow["next"])

    request.session[PENDING_KEY] = {"sub": sub, "email": email, "name": claims.get("name") or "",
                                    "next": flow["next"], "at": time.time()}
    return redirect("accounts:google_finish")


class GoogleFinishForm(forms.Form):
    full_name = forms.CharField(label=_lazy("Full name"), max_length=150)
    roles = forms.MultipleChoiceField(
        label=_lazy("I want to"), choices=[(r.value, r.label) for r in SIGNUP_ROLES],
        widget=forms.CheckboxSelectMultiple, initial=[Role.BUYER.value],
        help_text=_lazy("Choose one or more. You can change this later."),
    )
    agency_name = forms.CharField(label=_lazy("Agency name"), max_length=150, required=False)
    accept_terms = forms.BooleanField(label=_lazy("I accept the terms of use and privacy policy"), required=True)
    marketing_opt_in = forms.BooleanField(label=_lazy("Send me occasional product news"), required=False)

    def role_options(self):
        selected = self["roles"].value() or []
        return [(r.value, r.label, ROLE_HELP[r], r.value in selected) for r in SIGNUP_ROLES]

    def clean(self):
        data = super().clean()
        if Role.AGENCY.value in (data.get("roles") or []) and not data.get("agency_name", "").strip():
            self.add_error("agency_name", _("Enter your agency's name."))
        return data


def finish(request):
    pending = request.session.get(PENDING_KEY)
    if not is_enabled() or not pending or time.time() - pending["at"] > PENDING_TTL:
        request.session.pop(PENDING_KEY, None)
        return _fail(request, _("Your Google sign-in expired. Please try again."))
    form = GoogleFinishForm(request.POST or None, initial={"full_name": pending["name"]})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            if User.objects.filter(email__iexact=pending["email"]).exists():
                request.session.pop(PENDING_KEY, None)
                return _fail(request, _("An account with this email already exists. Sign in with Google again to link it."))
            now = timezone.now()
            user = User(email=pending["email"], full_name=data["full_name"].strip(), email_verified_at=now,
                        terms_accepted_at=now, marketing_opt_in=data.get("marketing_opt_in", False))
            user.set_roles([Role(r) for r in data["roles"]])
            user.set_unusable_password()
            user.save()
            Profile.objects.create(user=user)
            if user.is_agency:
                AgencyTeam.objects.create(owner=user, name=data["agency_name"].strip())
            if user.is_agent:
                AgentProfile.objects.create(user=user)
            SocialAccount.objects.create(user=user, provider=SocialAccount.GOOGLE, uid=pending["sub"], email=pending["email"])
        request.session.pop(PENDING_KEY, None)
        messages.success(request, _("Welcome to %(brand)s.") % {"brand": site_settings.get("site_name")})
        return _sign_in(request, user, pending["next"])
    return render(request, "accounts/google_finish.html", {"form": form, "email": pending["email"]})
