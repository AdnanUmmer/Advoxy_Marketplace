"""Sign-up, email verification, login and password reset flows."""

import re

import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.models import AgencyTeam, AgentProfile, User
from apps.accounts.tokens import make_email_token
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db

SIGNUP = {
    "full_name": "Ada Obi",
    "email": "Ada@Example.com",
    "roles": ["buyer", "landlord"],
    "password1": "Very-Secret-Pass-9",
    "password2": "Very-Secret-Pass-9",
    "accept_terms": "on",
}


def _link(body):
    return re.search(r"https?://\S+", body).group(0)


def test_signup_creates_user_with_roles_and_sends_verification(client):
    response = client.post(reverse("accounts:signup"), SIGNUP)
    assert response.status_code == 302 and response.url == reverse("accounts:verify_email_sent")
    user = User.objects.get(email="ada@example.com")
    assert user.is_buyer and user.is_landlord and not user.is_agent
    assert user.terms_accepted_at is not None and not user.is_email_verified
    assert hasattr(user, "profile")
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["ada@example.com"]
    assert "/accounts/verify/" in mail.outbox[0].body
    assert mail.outbox[0].alternatives  # HTML part present


def test_signup_requires_terms_and_rejects_duplicate_email(client, make_user):
    make_user(email="taken@example.com")
    data = {**SIGNUP, "email": "TAKEN@example.com"}
    data.pop("accept_terms")
    response = client.post(reverse("accounts:signup"), data)
    assert response.status_code == 200
    form = response.context["form"]
    assert "email" in form.errors and "accept_terms" in form.errors


def test_agency_signup_requires_name_and_creates_agency(client):
    data = {**SIGNUP, "email": "agency@example.com", "roles": ["agency"]}
    assert "agency_name" in client.post(reverse("accounts:signup"), data).context["form"].errors
    client.post(reverse("accounts:signup"), {**data, "agency_name": "Savanna Realty"})
    agency = AgencyTeam.objects.get(owner__email="agency@example.com")
    assert agency.name == "Savanna Realty" and agency.slug == "savanna-realty"


def test_agent_signup_creates_agent_profile(client):
    client.post(reverse("accounts:signup"), {**SIGNUP, "email": "agent@example.com", "roles": ["agent"]})
    assert AgentProfile.objects.filter(user__email="agent@example.com").exists()


def test_weak_password_rejected(client):
    data = {**SIGNUP, "password1": "12345", "password2": "12345"}
    assert "password1" in client.post(reverse("accounts:signup"), data).context["form"].errors


def test_verification_link_verifies_email(client):
    client.post(reverse("accounts:signup"), SIGNUP)
    link = _link(mail.outbox[0].body)
    response = client.get(link.split("localhost:8000")[-1] if "localhost" in link else link)
    assert response.status_code == 302
    assert User.objects.get(email="ada@example.com").is_email_verified


def test_tampered_or_stale_token_is_rejected(client, make_user):
    user = make_user(verified=False)
    token = make_email_token(user)
    assert client.get(reverse("accounts:verify_email_confirm", args=[token + "x"])).status_code == 400
    user.email = "changed@example.com"
    user.save()
    assert client.get(reverse("accounts:verify_email_confirm", args=[token])).status_code == 400
    user.refresh_from_db()
    assert not user.is_email_verified


def test_resend_verification(client, make_user):
    user = make_user(verified=False)
    client.force_login(user)
    client.post(reverse("accounts:verify_email_resend"))
    assert len(mail.outbox) == 1


def test_login_with_email_is_case_insensitive(client, make_user):
    user = make_user(email="kofi@example.com", is_buyer=True)
    response = client.post(reverse("accounts:login"), {"username": "KOFI@example.com", "password": PASSWORD})
    assert response.status_code == 302
    assert int(client.session["_auth_user_id"]) == user.pk


def test_logout_requires_post(client, make_user):
    client.force_login(make_user())
    client.post(reverse("accounts:logout"))
    assert "_auth_user_id" not in client.session


def test_password_reset_flow(client, make_user):
    user = make_user(email="reset@example.com")
    client.post(reverse("accounts:password_reset"), {"email": "reset@example.com"})
    assert len(mail.outbox) == 1
    path = re.search(r"/accounts/password/reset/[^\s\"]+/", mail.outbox[0].body).group(0)
    response = client.get(path, follow=True)  # Django swaps the token into the session
    assert response.context["validlink"]
    response = client.post(response.redirect_chain[-1][0], {"new_password1": "Brand-New-Pass-77", "new_password2": "Brand-New-Pass-77"})
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.check_password("Brand-New-Pass-77")


def test_password_reset_unknown_email_sends_nothing(client):
    response = client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})
    assert response.status_code == 302 and len(mail.outbox) == 0


def test_staff_login_rejects_non_staff(client, make_user):
    member = make_user(email="member@example.com", is_agent=True)
    response = client.post(reverse("accounts:staff_login"), {"username": member.email, "password": PASSWORD})
    assert response.status_code == 200 and "_auth_user_id" not in client.session
    staff = make_user(email="staff@example.com", is_staff=True)
    response = client.post(reverse("accounts:staff_login"), {"username": staff.email, "password": PASSWORD})
    assert response.status_code == 302 and response.url == reverse("accounts:staff_home")
