"""Sign in with Google: state/nonce/PKCE, claim validation, linking, new-account finish step."""

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse

from apps.accounts import google
from apps.accounts.models import AgencyTeam, SocialAccount, User

pytestmark = pytest.mark.django_db
CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture(autouse=True)
def google_settings(settings):
    settings.GOOGLE_CLIENT_ID = CLIENT_ID
    settings.GOOGLE_CLIENT_SECRET = "test-secret"


def _token(**overrides):
    claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "exp": int(time.time()) + 600,
              "sub": "1234567890", "email": "ada@gmail.com", "email_verified": True, "name": "Ada Obi"}
    claims.update(overrides)
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return {"id_token": f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig", "access_token": "x"}


def _begin(client, next_url=""):
    resp = client.get(reverse("accounts:google_start") + (f"?next={next_url}" if next_url else ""))
    assert resp.status_code == 302
    return parse_qs(urlparse(resp["Location"]).query)


def _complete(client, monkeypatch, next_url="", state=None, **claims):
    params = _begin(client, next_url)
    seen = {}

    def fake_exchange(code, redirect_uri, verifier):
        seen.update(code=code, redirect_uri=redirect_uri, verifier=verifier)
        return _token(nonce=claims.pop("nonce", params["nonce"][0]), **claims)

    monkeypatch.setattr(google, "exchange_code", fake_exchange)
    resp = client.get(reverse("accounts:google_callback"), {"state": state or params["state"][0], "code": "abc"})
    return resp, params, seen


def test_button_hidden_when_not_configured(client, settings):
    settings.GOOGLE_CLIENT_ID = ""
    assert "Sign in with Google" not in client.get(reverse("accounts:login")).content.decode()
    assert client.get(reverse("accounts:google_start")).status_code == 404


def test_button_shown_when_configured(client):
    assert "Sign in with Google" in client.get(reverse("accounts:login")).content.decode()
    assert "Sign up with Google" in client.get(reverse("accounts:signup")).content.decode()


def test_start_redirects_with_pkce_state_and_nonce(client):
    params = _begin(client)
    assert params["client_id"] == [CLIENT_ID]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["openid email profile"]
    assert params["redirect_uri"][0].endswith("/accounts/google/callback/")
    assert params["state"][0] and params["nonce"][0] and params["code_challenge"][0]


def test_pkce_verifier_matches_challenge(client, monkeypatch):
    import hashlib

    _resp, params, seen = _complete(client, monkeypatch)
    digest = base64.urlsafe_b64encode(hashlib.sha256(seen["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert digest == params["code_challenge"][0]


def test_new_user_finishes_signup(client, monkeypatch):
    resp, _p, _s = _complete(client, monkeypatch)
    assert resp["Location"] == reverse("accounts:google_finish")
    page = client.get(reverse("accounts:google_finish"))
    assert "ada@gmail.com" in page.content.decode()
    resp = client.post(reverse("accounts:google_finish"), {"full_name": "Ada Obi", "roles": ["renter", "agency"],
                                                           "agency_name": "Obi Homes", "accept_terms": "on"})
    assert resp.status_code == 302
    user = User.objects.get(email="ada@gmail.com")
    assert user.is_email_verified and user.is_renter and user.is_agency
    assert not user.has_usable_password()
    assert user.terms_accepted_at is not None
    assert AgencyTeam.objects.filter(owner=user, name="Obi Homes").exists()
    assert SocialAccount.objects.filter(user=user, uid="1234567890").exists()
    assert client.session["_auth_user_id"] == str(user.pk)


def test_finish_requires_terms(client, monkeypatch):
    _complete(client, monkeypatch)
    resp = client.post(reverse("accounts:google_finish"), {"full_name": "Ada", "roles": ["buyer"]})
    assert resp.status_code == 200
    assert not User.objects.filter(email="ada@gmail.com").exists()


def test_finish_without_pending_session_redirects(client):
    assert client.get(reverse("accounts:google_finish"))["Location"] == reverse("accounts:login")


def test_existing_account_is_linked_and_signed_in(client, monkeypatch, make_user):
    user = make_user(email="ada@gmail.com", is_buyer=True)
    resp, _p, _s = _complete(client, monkeypatch, next_url="/search/")
    assert resp["Location"] == "/search/"
    assert client.session["_auth_user_id"] == str(user.pk)
    assert SocialAccount.objects.get(uid="1234567890").user == user
    user.refresh_from_db()
    assert user.has_usable_password()  # verified accounts keep their password


def test_linking_unverified_account_disables_its_password(client, monkeypatch, make_user):
    user = make_user(email="ada@gmail.com", verified=False, is_buyer=True)
    _complete(client, monkeypatch)
    user.refresh_from_db()
    assert user.is_email_verified
    assert not user.has_usable_password()


def test_returning_user_matched_by_google_id_even_if_email_changed(client, monkeypatch, make_user):
    user = make_user(email="old@example.com", is_buyer=True)
    SocialAccount.objects.create(user=user, provider="google", uid="1234567890", email="old@example.com")
    _complete(client, monkeypatch, email="new@gmail.com")
    assert client.session["_auth_user_id"] == str(user.pk)


def test_unsafe_next_is_ignored(client, monkeypatch, make_user):
    make_user(email="ada@gmail.com", is_buyer=True)
    resp, _p, _s = _complete(client, monkeypatch, next_url="https://evil.example.com/")
    assert resp["Location"] == reverse("accounts:dashboard")


@pytest.mark.parametrize("claims", [
    {"aud": "someone-else"}, {"iss": "https://evil.example.com"}, {"exp": int(time.time()) - 10},
    {"nonce": "wrong"}, {"email_verified": False},
])
def test_bad_tokens_are_rejected(client, monkeypatch, claims):
    resp, _p, _s = _complete(client, monkeypatch, **claims)
    assert resp["Location"] == reverse("accounts:login")
    assert "_auth_user_id" not in client.session
    assert google.PENDING_KEY not in client.session


def test_state_mismatch_is_rejected(client, monkeypatch):
    resp, _p, _s = _complete(client, monkeypatch, state="forged")
    assert resp["Location"] == reverse("accounts:login")
    assert google.PENDING_KEY not in client.session


def test_callback_without_flow_is_rejected(client):
    resp = client.get(reverse("accounts:google_callback"), {"state": "x", "code": "y"})
    assert resp["Location"] == reverse("accounts:login")


def test_staff_and_suspended_accounts_cannot_use_google(client, monkeypatch, make_user):
    staff = make_user(email="ada@gmail.com", is_staff=True)
    _complete(client, monkeypatch)
    assert "_auth_user_id" not in client.session
    staff.is_staff = False
    staff.is_suspended = True
    staff.save()
    _complete(client, monkeypatch)
    assert "_auth_user_id" not in client.session


def test_token_exchange_failure_shows_error(client, monkeypatch):
    params = _begin(client)

    def boom(*args):
        raise google.GoogleError("down")

    monkeypatch.setattr(google, "exchange_code", boom)
    resp = client.get(reverse("accounts:google_callback"), {"state": params["state"][0], "code": "abc"})
    assert resp["Location"] == reverse("accounts:login")
