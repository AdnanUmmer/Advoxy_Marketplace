from celery import shared_task

from .services import end_featured_placements as _end


@shared_task
def end_featured_placements():
    """Hourly: unfeature listings whose paid placement has ended."""
    return _end()
