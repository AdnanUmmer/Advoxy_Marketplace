from django import template
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _l

register = template.Library()


@register.simple_tag(takes_context=True)
def sort_th(context, key, label, align="left"):
    """A sortable <th>. Needs `table` (staff.tables.Table) in context."""
    table = context["table"]
    query, aria, arrow = table.header(key)
    justify = "justify-end" if align == "right" else ""
    return format_html(
        '<th scope="col" aria-sort="{}" class="px-3 py-2.5 text-{} font-semibold">'
        '<a href="?{}" hx-get="?{}" hx-target="#table-region" hx-push-url="true" class="inline-flex items-center gap-1 hover:text-ink {}">'
        '{}<span aria-hidden="true" class="w-3 text-primary">{}</span></a></th>',
        aria, align, query, query, justify, label, arrow,
    )


@register.simple_tag(takes_context=True)
def page_qs(context, number):
    return context["table"].querystring(page=number)


@register.filter
def pct(value, total):
    try:
        return round(100 * float(value) / float(total), 1) if float(total) else 0
    except (TypeError, ValueError):
        return 0


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key, "")
    except AttributeError:
        return ""


AUDIT_LABELS = {
    "listing.approve": _l("Approved listing"), "listing.reject": _l("Rejected listing"),
    "listing.request_edits": _l("Asked for edits"), "listing.feature": _l("Featured"),
    "listing.unfeature": _l("Removed featured"), "listing.unpublish": _l("Unpublished"), "listing.delete": _l("Deleted listing"),
    "user.suspend": _l("Suspended user"), "user.unsuspend": _l("Unsuspended user"), "user.roles": _l("Changed roles"),
    "user.verification": _l("Set verification"), "verification.approve": _l("Approved licence"),
    "verification.reject": _l("Rejected licence"), "settings.update": _l("Changed settings"), "plan.update": _l("Changed plan"),
}


@register.filter
def audit_label(action):
    return AUDIT_LABELS.get(action, action)


@register.filter
def audit_badge(action):
    if action.endswith(("delete", "reject", "suspend", "unpublish")) and action != "user.unsuspend":
        return "badge-danger"
    if action.endswith(("approve", "unsuspend")):
        return "badge-success"
    if action.startswith(("settings.", "plan.")):
        return "badge-info"
    return "badge-neutral"


@register.filter
def field_label(key):
    """Readable name for a changed field in the audit log."""
    from apps.core.site_settings import FIELDS

    if key in FIELDS:
        return FIELDS[key].label
    return str(key).replace("_", " ").capitalize()
