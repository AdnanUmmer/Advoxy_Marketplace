from celery import shared_task

from .rules import expire_due_listings


@shared_task
def expire_listings():
    """Daily: move published listings past their expiry date to 'expired'."""
    return expire_due_listings()
