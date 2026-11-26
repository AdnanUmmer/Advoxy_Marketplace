from django import template
from django.utils.html import format_html

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
