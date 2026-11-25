from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    """Capabilities a user can hold. A user may hold several."""

    BUYER = "buyer", _("Buyer")
    RENTER = "renter", _("Renter")
    SELLER = "seller", _("Seller")
    LANDLORD = "landlord", _("Landlord")
    AGENT = "agent", _("Agent")
    AGENCY = "agency", _("Agency")
    ADMIN = "admin", _("Admin")


# Field name on User for each role flag (admin is is_staff).
ROLE_FIELDS = {
    Role.BUYER: "is_buyer",
    Role.RENTER: "is_renter",
    Role.SELLER: "is_seller",
    Role.LANDLORD: "is_landlord",
    Role.AGENT: "is_agent",
    Role.AGENCY: "is_agency",
    Role.ADMIN: "is_staff",
}

# Roles a member of the public may choose at sign-up.
SIGNUP_ROLES = [Role.BUYER, Role.RENTER, Role.SELLER, Role.LANDLORD, Role.AGENT, Role.AGENCY]


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, email_verified_at=timezone.now())
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """One account model; capabilities are boolean role flags."""

    email = models.EmailField(_("email address"), unique=True)
    full_name = models.CharField(_("full name"), max_length=150)

    is_buyer = models.BooleanField(_("buyer"), default=False)
    is_renter = models.BooleanField(_("renter"), default=False)
    is_seller = models.BooleanField(_("seller"), default=False)
    is_landlord = models.BooleanField(_("landlord"), default=False)
    is_agent = models.BooleanField(_("agent"), default=False)
    is_agency = models.BooleanField(_("agency"), default=False)

    is_staff = models.BooleanField(_("admin staff"), default=False)
    is_active = models.BooleanField(_("active"), default=True)
    is_suspended = models.BooleanField(_("suspended"), default=False)

    email_verified_at = models.DateTimeField(_("email verified at"), null=True, blank=True)
    terms_accepted_at = models.DateTimeField(_("terms accepted at"), null=True, blank=True)
    marketing_opt_in = models.BooleanField(_("marketing emails"), default=False)
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["-date_joined"]

    def __str__(self):
        return self.full_name or self.email

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return (self.full_name or self.email).split(" ")[0]

    # --- roles -----------------------------------------------------------
    @property
    def roles(self):
        return [role for role, field in ROLE_FIELDS.items() if getattr(self, field)]

    def has_role(self, role):
        return bool(getattr(self, ROLE_FIELDS[Role(role)]))

    def set_roles(self, roles):
        for role, field in ROLE_FIELDS.items():
            if role == Role.ADMIN:
                continue  # admin is never set through public role changes
            setattr(self, field, role in roles)

    @property
    def primary_role(self):
        """The role whose dashboard is shown first."""
        for role in (Role.ADMIN, Role.AGENCY, Role.AGENT, Role.LANDLORD, Role.SELLER, Role.RENTER, Role.BUYER):
            if self.has_role(role):
                return role
        return Role.BUYER

    @property
    def is_email_verified(self):
        return self.email_verified_at is not None

    @property
    def initials(self):
        parts = [p for p in (self.full_name or self.email).split() if p]
        return "".join(p[0] for p in parts[:2]).upper()


class Profile(models.Model):
    """Public-facing and contact details. Minimal data collection by design."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(_("phone"), max_length=32, blank=True)
    avatar = models.ImageField(_("photo"), upload_to="avatars/", blank=True)
    bio = models.TextField(_("about"), blank=True, max_length=2000)
    city = models.CharField(_("city"), max_length=100, blank=True)
    country = models.CharField(_("country"), max_length=100, blank=True)

    def __str__(self):
        return f"Profile of {self.user}"


class VerificationStatus(models.TextChoices):
    UNVERIFIED = "unverified", _("Not submitted")
    PENDING = "pending", _("Pending review")
    VERIFIED = "verified", _("Verified")
    REJECTED = "rejected", _("Rejected")


class AgencyTeam(models.Model):
    """An agency organisation with agent seats."""

    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_agency")
    name = models.CharField(_("agency name"), max_length=150)
    slug = models.SlugField(unique=True, max_length=170)
    logo = models.ImageField(_("logo"), upload_to="agencies/", blank=True)
    description = models.TextField(_("description"), blank=True)
    city = models.CharField(_("city"), max_length=100, blank=True)
    country = models.CharField(_("country"), max_length=100, blank=True)
    phone = models.CharField(_("phone"), max_length=32, blank=True)
    website = models.URLField(_("website"), blank=True)
    verification_status = models.CharField(
        max_length=12, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:150] or "agency"
            slug, n = base, 2
            while AgencyTeam.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_verified(self):
        return self.verification_status == VerificationStatus.VERIFIED


class AgentProfile(models.Model):
    """Agent details. Agency is optional: agents can work independently."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_profile")
    agency = models.ForeignKey(
        AgencyTeam, on_delete=models.SET_NULL, null=True, blank=True, related_name="agents"
    )
    license_number = models.CharField(_("license number"), max_length=80, blank=True)
    specialties = models.CharField(_("specialties"), max_length=200, blank=True)
    years_experience = models.PositiveSmallIntegerField(_("years of experience"), null=True, blank=True)
    verification_status = models.CharField(
        max_length=12, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )

    def __str__(self):
        return f"Agent {self.user}"

    @property
    def is_verified(self):
        return self.verification_status == VerificationStatus.VERIFIED


class VerificationDocument(models.Model):
    """License document uploaded by an agent or agency for admin review."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verification_documents")
    agency = models.ForeignKey(AgencyTeam, on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    document = models.FileField(_("license document"), upload_to="verification/%Y/%m/")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Verification for {self.user} ({self.status})"

    def get_absolute_url(self):
        return reverse("accounts:dashboard")
