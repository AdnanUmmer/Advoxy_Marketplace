"""Django's built-in admin is kept for superuser maintenance only.
The staff-facing admin dashboard is a custom app (milestone 5)."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AgencyTeam, AgentProfile, Profile, User, VerificationDocument


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-date_joined"]
    list_display = ["email", "full_name", "primary_role", "is_staff", "is_suspended", "date_joined"]
    list_filter = ["is_buyer", "is_renter", "is_seller", "is_landlord", "is_agent", "is_agency", "is_staff", "is_suspended"]
    search_fields = ["email", "full_name"]
    fieldsets = (
        (None, {"fields": ("email", "full_name", "password")}),
        ("Roles", {"fields": ("is_buyer", "is_renter", "is_seller", "is_landlord", "is_agent", "is_agency")}),
        ("Status", {"fields": ("is_active", "is_suspended", "email_verified_at", "terms_accepted_at", "marketing_opt_in")}),
        ("Staff", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "full_name", "password1", "password2")}),)


admin.site.register(Profile)
admin.site.register(AgencyTeam)
admin.site.register(AgentProfile)
admin.site.register(VerificationDocument)
