"""
Role-based permission rules. Views use the decorators/mixins below; the rules
themselves are plain functions so they are easy to test.
"""

from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from .models import Role

LISTER_ROLES = (Role.SELLER, Role.LANDLORD, Role.AGENT, Role.AGENCY)


def is_active_member(user):
    return bool(user and user.is_authenticated and user.is_active and not user.is_suspended)


def can_browse(user):
    """Everyone, including anonymous visitors, can browse."""
    return True


def can_save_and_inquire(user):
    """Saving listings, saved searches, inquiries and messages: any verified member."""
    return is_active_member(user) and user.is_email_verified


def can_list_properties(user):
    """Owners (seller/landlord), agents and agencies may create listings.

    Capacity (how many) is enforced separately by listing limits.
    """
    return can_save_and_inquire(user) and any(user.has_role(r) for r in LISTER_ROLES)


def can_manage_agency(user):
    return is_active_member(user) and user.has_role(Role.AGENCY)


def can_access_staff(user):
    return is_active_member(user) and user.is_staff


def role_required(*roles):
    """Allow the view only for users holding at least one of `roles`."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not is_active_member(user) or not any(user.has_role(r) for r in roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def verified_email_required(view):
    """Require a verified email; otherwise send the user to the verification prompt."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not user.is_email_verified:
            messages.info(request, _("Please verify your email address to continue."))
            return redirect("accounts:verify_email_sent")
        return view(request, *args, **kwargs)

    return wrapped


def staff_required(view):
    """Function-view version of StaffRequiredMixin."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.STAFF_LOGIN_URL)
        if not can_access_staff(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


class StaffRequiredMixin(AccessMixin):
    """Admin dashboard views. Anonymous users go to the separate staff login."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.STAFF_LOGIN_URL)
        if not can_access_staff(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
