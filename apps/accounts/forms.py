from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.emails import send_templated_email

from .models import SIGNUP_ROLES, AgencyTeam, AgentProfile, Profile, Role, User

ROLE_HELP = {
    Role.BUYER: _("Browse, save and contact sellers."),
    Role.RENTER: _("Find a place to rent."),
    Role.SELLER: _("Sell a property you own."),
    Role.LANDLORD: _("Let out a property you own."),
    Role.AGENT: _("List properties as a licensed agent."),
    Role.AGENCY: _("Run a team of agents."),
}


class SignupForm(forms.Form):
    full_name = forms.CharField(label=_("Full name"), max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(label=_("Email"), widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    roles = forms.MultipleChoiceField(
        label=_("I want to"),
        choices=[(r.value, r.label) for r in SIGNUP_ROLES],
        widget=forms.CheckboxSelectMultiple,
        initial=[Role.BUYER.value],
        help_text=_("Choose one or more. You can change this later."),
    )
    agency_name = forms.CharField(label=_("Agency name"), max_length=150, required=False)
    password1 = forms.CharField(
        label=_("Password"), strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    password2 = forms.CharField(
        label=_("Confirm password"), strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    accept_terms = forms.BooleanField(label=_("I accept the terms of use and privacy policy"), required=True)
    marketing_opt_in = forms.BooleanField(label=_("Send me occasional product news"), required=False)

    def role_options(self):
        """(value, label, help, checked) for the custom role picker template."""
        selected = self["roles"].value() or []
        return [(r.value, r.label, ROLE_HELP[r], r.value in selected) for r in SIGNUP_ROLES]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(_("An account with this email already exists."))
        return email

    def clean(self):
        data = super().clean()
        if Role.AGENCY.value in (data.get("roles") or []) and not data.get("agency_name", "").strip():
            self.add_error("agency_name", _("Enter your agency's name."))
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("The two passwords do not match."))
        if p1:
            probe = User(email=data.get("email", ""), full_name=data.get("full_name", ""))
            try:
                password_validation.validate_password(p1, probe)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return data

    def save(self):
        data = self.cleaned_data
        user = User(email=data["email"], full_name=data["full_name"].strip())
        user.set_roles([Role(r) for r in data["roles"]])
        user.set_password(data["password1"])
        user.terms_accepted_at = timezone.now()
        user.marketing_opt_in = data.get("marketing_opt_in", False)
        user.save()
        Profile.objects.create(user=user)
        if user.is_agency:
            AgencyTeam.objects.create(owner=user, name=data["agency_name"].strip())
        if user.is_agent:
            AgentProfile.objects.create(user=user)
        return user


class EmailLoginForm(AuthenticationForm):
    username = forms.EmailField(label=_("Email"), widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}))

    error_messages = {
        "invalid_login": _("That email and password don't match an account."),
        "inactive": _("This account is not active."),
    }


class StaffLoginForm(EmailLoginForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError(_("This sign-in is for staff only."), code="not_staff")


class QueuedPasswordResetForm(PasswordResetForm):
    """Sends the reset email through Celery using our branded templates."""

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None):
        context = {k: v for k, v in context.items() if k in ("uid", "token", "protocol", "domain")}
        send_templated_email("password_reset", to_email, context)

    def get_users(self, email):
        return User.objects.filter(email__iexact=email, is_active=True, is_suspended=False)


# ---------------------------------------------------------------------------
# Profile editing (milestone 7)
# ---------------------------------------------------------------------------
class _ImageCleanMixin:
    """Re-encode uploaded images (drops EXIF/GPS data, downscales)."""

    def _clean_image(self, field):
        upload = self.cleaned_data.get(field)
        if upload and hasattr(upload, "content_type"):
            from apps.listings.photos import normalize_image

            return normalize_image(upload)
        return upload


class ProfileForm(_ImageCleanMixin, forms.ModelForm):
    full_name = forms.CharField(label=_("Full name"), max_length=150)

    class Meta:
        model = Profile
        fields = ["phone", "city", "country", "bio", "avatar"]
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}
        help_texts = {"phone": _("Shown to people you reply to and on your public agent profile.")}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["full_name"].initial = user.full_name
        self.order_fields(["full_name", "phone", "city", "country", "bio", "avatar"])

    def clean_avatar(self):
        return self._clean_image("avatar")

    def save(self, commit=True):
        profile = super().save(commit)
        self.user.full_name = self.cleaned_data["full_name"].strip()
        self.user.save(update_fields=["full_name"])
        return profile


class AgentDetailsForm(forms.ModelForm):
    class Meta:
        model = AgentProfile
        fields = ["license_number", "specialties", "years_experience"]
        help_texts = {"specialties": _("For example: rentals in Westlands, luxury villas, first-time buyers.")}


class AgencyForm(_ImageCleanMixin, forms.ModelForm):
    website = forms.URLField(label=_("Website"), required=False, assume_scheme="https")

    class Meta:
        model = AgencyTeam
        fields = ["name", "logo", "description", "city", "country", "phone", "website"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def clean_logo(self):
        return self._clean_image("logo")
