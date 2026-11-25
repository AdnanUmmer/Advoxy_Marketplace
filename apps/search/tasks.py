from celery import shared_task

from .digest import send_digests


@shared_task
def send_saved_search_digests():
    """Daily: email each user the new listings matching their saved searches."""
    return send_digests()
