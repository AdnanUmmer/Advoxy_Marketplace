from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Email login, case-insensitive. Suspended accounts cannot sign in."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = (kwargs.get("email") or username or "").strip().lower()
        return super().authenticate(request, username=email, password=password)

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and not getattr(user, "is_suspended", False)
