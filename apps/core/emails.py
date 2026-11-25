"""
Transactional email helper. Every email has three templates:
  templates/emails/<name>_subject.txt, <name>.txt, <name>.html
Sending is always queued through Celery.
"""

from django.conf import settings
from django.template.loader import render_to_string

from config.brand import BRAND

from .tasks import send_email_task


def build_context(extra=None):
    ctx = {"brand": BRAND, "site_url": settings.SITE_URL}
    ctx.update(extra or {})
    return ctx


def render_email(name, context):
    ctx = build_context(context)
    subject = " ".join(render_to_string(f"emails/{name}_subject.txt", ctx).split())
    text_body = render_to_string(f"emails/{name}.txt", ctx)
    html_body = render_to_string(f"emails/{name}.html", ctx)
    return subject, text_body, html_body


def send_templated_email(name, to, context=None):
    if isinstance(to, str):
        to = [to]
    subject, text_body, html_body = render_email(name, context or {})
    send_email_task.delay(subject, list(to), text_body, html_body, settings.DEFAULT_FROM_EMAIL)
