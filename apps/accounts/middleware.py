from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils.translation import gettext as _


class SuspendedUserMiddleware:
    """Sign out an account as soon as staff suspend it (it can't sign back in either)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_suspended:
            logout(request)
            messages.error(request, _("This account has been suspended. Contact support if you think this is a mistake."))
            return redirect("accounts:login")
        return self.get_response(request)
