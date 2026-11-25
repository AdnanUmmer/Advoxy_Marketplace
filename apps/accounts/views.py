from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.core.emails import send_templated_email

from .forms import EmailLoginForm, QueuedPasswordResetForm, SignupForm, StaffLoginForm
from .models import Role, User
from .permissions import StaffRequiredMixin
from .tokens import make_email_token, read_email_token


def send_verification_email(user):
    link = reverse("accounts:verify_email_confirm", args=[make_email_token(user)])
    send_templated_email("verify_email", user.email, {"user_name": user.get_short_name(), "path": link})


def signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        send_verification_email(user)
        login(request, user, backend="apps.accounts.backends.EmailBackend")
        return redirect("accounts:verify_email_sent")
    return render(request, "accounts/signup.html", {"form": form})


@login_required
def verify_email_sent(request):
    if request.user.is_email_verified:
        return redirect("accounts:dashboard")
    return render(request, "accounts/verify_email_sent.html")


@login_required
@require_POST
def verify_email_resend(request):
    if not request.user.is_email_verified:
        send_verification_email(request.user)
        messages.success(request, _("We sent a new verification link to %(email)s.") % {"email": request.user.email})
    return redirect("accounts:verify_email_sent")


def verify_email_confirm(request, token):
    parsed = read_email_token(token)
    user = None
    if parsed:
        uid, email = parsed
        user = User.objects.filter(pk=uid, email=email).first()
    if user is None:
        return render(request, "accounts/verify_email_invalid.html", status=400)
    if not user.is_email_verified:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
    messages.success(request, _("Your email is verified. Welcome aboard."))
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    return redirect("accounts:login")


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailLoginForm
    redirect_authenticated_user = True


class StaffLoginView(auth_views.LoginView):
    template_name = "accounts/staff_login.html"
    authentication_form = StaffLoginForm
    redirect_authenticated_user = False

    def get_default_redirect_url(self):
        return reverse("accounts:staff_home")


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = QueuedPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


DASHBOARD_TEMPLATES = {
    Role.BUYER: "accounts/dashboards/buyer.html",
    Role.RENTER: "accounts/dashboards/renter.html",
    Role.SELLER: "accounts/dashboards/owner.html",
    Role.LANDLORD: "accounts/dashboards/owner.html",
    Role.AGENT: "accounts/dashboards/agent.html",
    Role.AGENCY: "accounts/dashboards/agency.html",
}


@login_required
def dashboard(request):
    """Each role has its own home screen. Users with several roles can switch."""
    user = request.user
    if user.is_staff and not request.GET.get("as"):
        return redirect("accounts:staff_home")
    public_roles = [r for r in user.roles if r in DASHBOARD_TEMPLATES]
    requested = request.GET.get("as")
    role = Role(requested) if requested in [r.value for r in public_roles] else None
    if role is None:
        role = user.primary_role if user.primary_role in DASHBOARD_TEMPLATES else (public_roles or [Role.BUYER])[0]
    context = {
        "dashboard_role": role,
        "switchable_roles": public_roles,
        "agency": getattr(user, "owned_agency", None) if user.is_agency else None,
        "agent_profile": getattr(user, "agent_profile", None) if user.is_agent else None,
    }
    if role in (Role.SELLER, Role.LANDLORD, Role.AGENT):
        from apps.listings.views import owner_dashboard_context

        context.update(owner_dashboard_context(request, user))
    return render(request, DASHBOARD_TEMPLATES[role], context)


class StaffHomeView(StaffRequiredMixin, TemplateView):
    """Staff landing page. The full admin dashboard arrives in milestone 5."""

    template_name = "accounts/staff_home.html"
