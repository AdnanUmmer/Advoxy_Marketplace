"""Audit log helper: `audit.record(request, "listing.approve", listing, note=reason)`."""

from .models import AuditLog


def _client_ip(request):
    if request is None:
        return None
    # Nginx sets X-Real-IP; fall back to the socket address.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or None


def record(request, action, target=None, changes=None, note="", actor=None):
    actor = actor or (getattr(request, "user", None) if request else None)
    if actor is not None and not actor.is_authenticated:
        actor = None
    target_type = target_id = target_label = ""
    if target is not None:
        target_type = target._meta.model_name
        target_id = str(target.pk)
        target_label = str(target)[:200]
    return AuditLog.objects.create(
        actor=actor, actor_label=actor.email if actor else "system", action=action,
        target_type=target_type, target_id=target_id, target_label=target_label,
        changes=changes or {}, note=(note or "")[:500], ip_address=_client_ip(request),
    )


def record_many(request, action, targets, note=""):
    """One entry per target (bulk actions)."""
    actor = getattr(request, "user", None)
    ip = _client_ip(request)
    AuditLog.objects.bulk_create([
        AuditLog(actor=actor, actor_label=actor.email, action=action, target_type=t._meta.model_name,
                 target_id=str(t.pk), target_label=str(t)[:200], note=(note or "")[:500], ip_address=ip)
        for t in targets
    ])
