from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.translation import gettext as _

register = template.Library()


@register.filter
def money(value, decimals=0):
    """Format an amount in the configured currency, e.g. $1,250,000."""
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        return value
    amount = round(amount, int(decimals))
    text = intcomma(f"{amount:.{int(decimals)}f}")
    return f"{settings.CURRENCY_SYMBOL}{text}"


@register.filter
def price_suffix(listing):
    """'/ month' for rentals, nothing for sales."""
    return _("/ month") if getattr(listing, "purpose", "") == "rent" else ""


@register.simple_tag(takes_context=True)
def active(context, url_name_prefix):
    match = context["request"].resolver_match
    name = f"{match.namespace}:{match.url_name}" if match and match.namespace else (match.url_name if match else "")
    return "is-active" if name.startswith(url_name_prefix) else ""


@register.filter
def field_widget(bound_field, css="field-input"):
    """Render a form field's widget with design-system classes and ARIA wiring."""
    attrs = {"class": css}
    described = []
    if bound_field.help_text:
        described.append(f"{bound_field.auto_id}_help")
    if bound_field.errors:
        attrs["aria-invalid"] = "true"
        described.append(f"{bound_field.auto_id}_error")
    if described:
        attrs["aria-describedby"] = " ".join(described)
    return bound_field.as_widget(attrs=attrs)


@register.filter
def is_in(value, container):
    try:
        return value in container
    except TypeError:
        return False
