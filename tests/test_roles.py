"""Role model and role-based permissions."""

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts import permissions as perms
from apps.accounts.models import Role
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_user_can_hold_several_roles(make_user):
    user = make_user(is_buyer=True, is_landlord=True)
    assert set(user.roles) == {Role.BUYER, Role.LANDLORD}
    assert user.has_role("landlord") and not user.has_role(Role.AGENT)


def test_primary_role_prefers_professional_roles(make_user):
    assert make_user(is_buyer=True, is_agent=True).primary_role == Role.AGENT
    assert make_user(is_renter=True).primary_role == Role.RENTER
    assert make_user().primary_role == Role.BUYER  # no flags falls back to buyer
    assert make_user(is_staff=True, is_buyer=True).primary_role == Role.ADMIN


def test_set_roles_never_grants_admin(make_user):
    user = make_user(is_buyer=True)
    user.set_roles([Role.ADMIN, Role.SELLER])
    assert user.is_seller and not user.is_buyer
    assert not user.is_staff


@pytest.mark.parametrize(
    "flags, can_list",
    [
        ({"is_buyer": True}, False),
        ({"is_renter": True}, False),
        ({"is_seller": True}, True),
        ({"is_landlord": True}, True),
        ({"is_agent": True}, True),
        ({"is_agency": True}, True),
    ],
)
def test_who_can_list_properties(make_user, flags, can_list):
    assert perms.can_list_properties(make_user(**flags)) is can_list


def test_unverified_or_suspended_users_cannot_list_or_inquire(make_user):
    unverified = make_user(verified=False, is_seller=True)
    suspended = make_user(is_seller=True, is_suspended=True)
    for user in (unverified, suspended):
        assert not perms.can_list_properties(user)
        assert not perms.can_save_and_inquire(user)


def test_staff_access_only_for_active_staff(make_user):
    assert perms.can_access_staff(make_user(is_staff=True))
    assert not perms.can_access_staff(make_user(is_agent=True))
    assert not perms.can_access_staff(make_user(is_staff=True, is_suspended=True))


def test_agency_management_only_for_agency_role(make_user):
    assert perms.can_manage_agency(make_user(is_agency=True))
    assert not perms.can_manage_agency(make_user(is_agent=True))


def test_role_required_decorator(make_user):
    from django.contrib.auth.models import AnonymousUser
    from django.core.exceptions import PermissionDenied

    view = perms.role_required(Role.AGENT, Role.AGENCY)(lambda request: HttpResponse("ok"))
    rf = RequestFactory()

    request = rf.get("/x/")
    request.user = make_user(is_agent=True)
    assert view(request).status_code == 200

    request.user = make_user(is_buyer=True)
    with pytest.raises(PermissionDenied):
        view(request)

    request.user = AnonymousUser()
    response = view(request)
    assert response.status_code == 302 and reverse("accounts:login") in response.url


def test_staff_area_redirects_anonymous_to_staff_login(client):
    response = client.get(reverse("accounts:staff_home"))
    assert response.status_code == 302
    assert reverse("accounts:staff_login") in response.url


def test_staff_area_forbidden_for_members(client, make_user):
    client.force_login(make_user(is_agent=True))
    assert client.get(reverse("accounts:staff_home")).status_code == 403


def test_staff_area_open_to_staff(client, make_user):
    client.force_login(make_user(is_staff=True))
    assert client.get(reverse("accounts:staff_home")).url == reverse("staff:overview")
    assert client.get(reverse("staff:overview")).status_code == 200


@pytest.mark.parametrize(
    "flags, template",
    [
        ({"is_buyer": True}, "accounts/dashboards/buyer.html"),
        ({"is_renter": True}, "accounts/dashboards/renter.html"),
        ({"is_seller": True}, "accounts/dashboards/owner.html"),
        ({"is_landlord": True}, "accounts/dashboards/owner.html"),
        ({"is_agent": True}, "accounts/dashboards/agent.html"),
        ({"is_agency": True}, "accounts/dashboards/agency.html"),
    ],
)
def test_each_role_gets_its_own_dashboard(client, make_user, flags, template):
    client.force_login(make_user(**flags))
    response = client.get(reverse("accounts:dashboard"))
    assert response.status_code == 200
    assert template in [t.name for t in response.templates]


def test_dashboard_switch_only_to_held_roles(client, make_user):
    client.force_login(make_user(is_buyer=True, is_landlord=True))
    as_buyer = client.get(reverse("accounts:dashboard") + "?as=buyer")
    assert "accounts/dashboards/buyer.html" in [t.name for t in as_buyer.templates]
    as_agent = client.get(reverse("accounts:dashboard") + "?as=agent")  # not held: falls back
    assert "accounts/dashboards/owner.html" in [t.name for t in as_agent.templates]


def test_staff_dashboard_redirects_to_staff_home(client, make_user):
    client.force_login(make_user(is_staff=True))
    response = client.get(reverse("accounts:dashboard"))
    assert response.status_code == 302 and response.url == reverse("staff:overview")


def test_suspended_user_cannot_sign_in(client, make_user):
    user = make_user(is_buyer=True, is_suspended=True)
    response = client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    assert response.status_code == 200  # form re-rendered with error
    assert "_auth_user_id" not in client.session
