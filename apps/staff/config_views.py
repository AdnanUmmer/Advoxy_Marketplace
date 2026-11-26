"""Staff settings, subscription plans, audit log and email previews (milestone 8)."""

import hashlib
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.forms import modelformset_factory
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.permissions import staff_required
from apps.billing.models import Plan
from apps.core import audit, site_settings
from apps.core.emails import build_context
from apps.core.models import AuditLog

from .tables import Table
from .views import render_staff


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingsForm(forms.Form):
    clear_logo = forms.BooleanField(required=False, label=gettext_lazy("Use the default logo"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        values = site_settings.all_values()
        for key, f in site_settings.FIELDS.items():
            common = {"label": f.label, "help_text": f.help, "required": f.kind in ("int", "money") or key in ("site_name", "currency_code", "currency_symbol")}
            if f.kind == "int":
                field = forms.IntegerField(min_value=f.min_value, max_value=f.max_value, initial=values[key], **common)
            elif f.kind == "money":
                field = forms.DecimalField(min_value=Decimal(f.min_value), max_value=Decimal(f.max_value), decimal_places=2,
                                           initial=values[key], **common)
            elif f.kind == "file":
                field = forms.ImageField(**{**common, "required": False})
            else:
                field = forms.CharField(max_length=120, initial=values[key], **common)
            self.fields[key] = field
        self.fields["support_email"] = forms.EmailField(label=site_settings.FIELDS["support_email"].label,
                                                        initial=values["support_email"], required=True)
        self.order_fields(list(site_settings.FIELDS) + ["clear_logo"])

    def clean_currency_code(self):
        code = self.cleaned_data["currency_code"].strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise forms.ValidationError(_("Use a three-letter code such as USD, KES or NGN."))
        return code

    def clean_currency_symbol(self):
        symbol = self.cleaned_data["currency_symbol"].strip()
        if len(symbol) > 5:
            raise forms.ValidationError(_("Keep the symbol to five characters or fewer."))
        return symbol

    def clean_logo(self):
        upload = self.cleaned_data.get("logo")
        if upload and hasattr(upload, "content_type"):
            from apps.listings.photos import normalize_image

            return normalize_image(upload)
        return upload

    def groups(self):
        out = []
        for gkey, glabel in site_settings.GROUPS:
            out.append((glabel, [self[k] for k, f in site_settings.FIELDS.items() if f.group == gkey]))
        return out


PlanFormSet = modelformset_factory(
    Plan, fields=["name", "price_monthly", "listing_limit", "seats", "description", "is_active"], extra=0,
    widgets={"description": forms.TextInput()},
)


def _plan_queryset():
    return Plan.objects.order_by("sort_order", "price_monthly")


@staff_required
def settings_page(request):
    form = SettingsForm()
    plans = PlanFormSet(queryset=_plan_queryset(), prefix="plans")
    section = request.POST.get("section") if request.method == "POST" else None

    if section == "site":
        form = SettingsForm(request.POST, request.FILES)
        if form.is_valid():
            data = {k: v for k, v in form.cleaned_data.items() if k in site_settings.FIELDS and k != "logo"}
            upload = form.cleaned_data.get("logo")
            if upload:
                content = upload.read()
                name = f"brand/logo-{hashlib.sha256(content).hexdigest()[:12]}.{upload.name.rsplit('.', 1)[-1].lower()}"
                data["logo"] = default_storage.save(name, ContentFile(content))
            elif form.cleaned_data.get("clear_logo"):
                data["logo"] = ""
            changes = site_settings.save(data, request.user)
            if changes:
                audit.record(request, "settings.update", changes={k: list(v) for k, v in changes.items()})
                messages.success(request, _("Settings saved."))
            else:
                messages.info(request, _("Nothing changed."))
            return redirect("staff:settings")
    elif section == "plans":
        plans = PlanFormSet(request.POST, queryset=_plan_queryset(), prefix="plans")
        if plans.is_valid():
            for pf in plans.forms:
                if pf.has_changed():
                    changes = {f: [str(pf.initial.get(f)), str(pf.cleaned_data.get(f))] for f in pf.changed_data}
                    plan = pf.save()
                    audit.record(request, "plan.update", plan, changes=changes)
            messages.success(request, _("Plans saved. New prices apply to new subscriptions."))
            return redirect("staff:settings")

    return render_staff(request, "staff/settings.html", {"form": form, "plans": plans,
                                                         "logo_url": site_settings.logo_url()})


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
AUDIT_COLUMNS = {"when": "created_at", "actor": "actor_label", "action": "action"}
AUDIT_AREAS = [
    ("listing", gettext_lazy("Listings")), ("user", gettext_lazy("Users")),
    ("verification", gettext_lazy("Verifications")), ("settings", gettext_lazy("Settings")),
    ("plan", gettext_lazy("Plans")),
]


@staff_required
def audit_log(request):
    qs = AuditLog.objects.select_related("actor")
    g = request.GET
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(actor_label__icontains=q) | Q(target_label__icontains=q) | Q(note__icontains=q) | Q(action__icontains=q))
    if g.get("area") in dict(AUDIT_AREAS):
        qs = qs.filter(action__startswith=f"{g['area']}.")
    start, end = parse_date(g.get("from", "") or ""), parse_date(g.get("to", "") or "")
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    if g.get("target_type") and g.get("target_id"):
        qs = qs.filter(target_type=g["target_type"], target_id=g["target_id"])
    table = Table(request, qs, AUDIT_COLUMNS, default="-when", per_page=50)
    context = {"table": table, "areas": AUDIT_AREAS,
               "filtered": any(g.get(k) for k in ("q", "area", "from", "to", "target_id")),
               "week_count": AuditLog.objects.filter(created_at__gte=timezone.now() - timedelta(days=7)).count()}
    return render_staff(request, "staff/audit.html", context, partial="staff/_audit_table.html")


# ---------------------------------------------------------------------------
# Email previews
# ---------------------------------------------------------------------------
def _sample_contexts():
    from apps.listings.models import Listing

    site = build_context()["site_url"]
    title = "Light-filled 3-bed apartment in Kilimani"
    sample_listings = list(Listing.objects.published().order_by("-published_at")[:3])
    return {
        "verify_email": (_("Confirm your email"), {"user_name": "Kwame", "path": "/accounts/verify/sample-token/"}),
        "password_reset": (_("Password reset"), {"protocol": site.split("://")[0], "domain": site.split("://")[-1],
                                                "uid": "MQ", "token": "sample-token"}),
        "new_inquiry": (_("New inquiry"), {"owner_name": "Wanjiru", "listing_title": title, "listing_path": "/listings/1/sample/",
                                          "thread_path": "/messages/1/", "name": "Kwame Mensah", "email": "kwame@example.com",
                                          "phone": "+233 20 000 0000",
                                          "message": "Is the apartment still available for a viewing this Saturday?"}),
        "new_message": (_("New message"), {"recipient_name": "Wanjiru", "sender_name": "Kwame Mensah", "listing_title": title,
                                          "thread_path": "/messages/1/", "preview": "Great, see you at 10am."}),
        "listing_approved": (_("Listing approved"), {"user_name": "Wanjiru", "listing_title": title, "path": "/listings/1/sample/"}),
        "listing_rejected": (_("Listing sent back"), {"user_name": "Wanjiru", "listing_title": title, "path": "/listings/1/edit/",
                                                     "note": "Please add at least three photos of the interior.",
                                                     "changes_requested": True}),
        "verification_approved": (_("Verification approved"), {"user_name": "Yusuf"}),
        "verification_rejected": (_("Verification rejected"), {"user_name": "Yusuf", "reason": "The license number is not readable."}),
        "payment_receipt": (_("Payment receipt"), {"user_name": "Wanjiru", "description": "Featured placement for 14 days",
                                                  "amount": Decimal("25.00"), "currency": site_settings.get("currency_code"),
                                                  "paid_at": timezone.now(), "reference": "ADV-000123", "path": "/billing/"}),
        "saved_search_digest": (_("Saved-search digest"), {
            "user_name": "Zanele", "total": len(sample_listings), "manage_url": "/search/saved/",
            "sections": [{"name": "Homes in Nairobi", "listings": sample_listings, "more": False, "url": "/search/?city=Nairobi"}]}),
        "agency_invitation": (_("Agency invitation"), {"inviter_name": "Nadia El-Sayed", "agency_name": "Meridian Homes",
                                                      "path": "/invitations/sample/"}),
    }


@staff_required
def email_previews(request):
    samples = _sample_contexts()
    current = request.GET.get("t") if request.GET.get("t") in samples else next(iter(samples))
    ctx = build_context(samples[current][1])
    subject = render_to_string(f"emails/{current}_subject.txt", ctx).strip()
    text = render_to_string(f"emails/{current}.txt", ctx)
    html = render_to_string(f"emails/{current}.html", ctx)
    return render_staff(request, "staff/emails.html", {
        "templates": [(k, v[0]) for k, v in samples.items()], "current": current, "subject": subject, "text": text,
        "html": html,
    })


@staff_required
def email_preview_html(request, name):
    samples = _sample_contexts()
    if name not in samples:
        raise Http404
    html = render_to_string(f"emails/{name}.html", build_context(samples[name][1]))
    response = HttpResponse(html)
    response["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src * data:; style-src 'unsafe-inline'"
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response
