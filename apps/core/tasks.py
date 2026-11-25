from celery import shared_task
from django.core.mail import EmailMultiAlternatives


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def send_email_task(self, subject, to, text_body, html_body=None, from_email=None):
    msg = EmailMultiAlternatives(subject=subject, body=text_body, from_email=from_email, to=to)
    if html_body:
        msg.attach_alternative(html_body, "text/html")
    msg.send()
