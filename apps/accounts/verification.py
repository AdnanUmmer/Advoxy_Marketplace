"""License verification for agents and agencies: upload by the member, review by staff."""

import os

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.emails import send_templated_email

from .models import VerificationDocument, VerificationStatus

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_BYTES = 10 * 1024 * 1024
PDF_MAGIC, JPG_MAGIC, PNG_MAGIC = b"%PDF", b"\xff\xd8\xff", b"\x89PNG"


def _targets(user):
    """The agent profile and/or agency whose badge this document supports."""
    agent = getattr(user, "agent_profile", None) if user.is_agent else None
    agency = getattr(user, "owned_agency", None) if user.is_agency else None
    return agent, agency


def validate_document(upload):
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(_("Upload a PDF, JPG or PNG file."))
    if upload.size > MAX_BYTES:
        raise ValidationError(_("The file is larger than 10 MB."))
    head = upload.read(8)
    upload.seek(0)
    if not (head.startswith(PDF_MAGIC) or head.startswith(JPG_MAGIC) or head.startswith(PNG_MAGIC)):
        raise ValidationError(_("That file doesn't look like a PDF or image."))


@transaction.atomic
def submit_document(user, upload):
    agent, agency = _targets(user)
    if not (agent or agency):
        raise ValidationError(_("Only agents and agencies can request verification."))
    validate_document(upload)
    doc = VerificationDocument.objects.create(user=user, agency=agency, document=upload)
    for target in (agent, agency):
        if target and target.verification_status != VerificationStatus.VERIFIED:
            target.verification_status = VerificationStatus.PENDING
            target.save(update_fields=["verification_status"])
    return doc


@transaction.atomic
def review_document(doc, staff_user, approve, reason=""):
    if not staff_user.is_staff:
        raise PermissionError("staff only")
    if doc.status != VerificationDocument.Status.PENDING:
        raise ValidationError(_("This document has already been reviewed."))
    if not approve and not reason.strip():
        raise ValidationError(_("Give a reason so the applicant knows what to fix."))
    doc.status = VerificationDocument.Status.APPROVED if approve else VerificationDocument.Status.REJECTED
    doc.rejection_reason = "" if approve else reason.strip()
    doc.reviewed_by = staff_user
    doc.reviewed_at = timezone.now()
    doc.save()
    agent, agency = _targets(doc.user)
    status = VerificationStatus.VERIFIED if approve else VerificationStatus.REJECTED
    for target in (agent, agency):
        if target:
            target.verification_status = status
            target.save(update_fields=["verification_status"])
    user = doc.user
    transaction.on_commit(lambda: send_templated_email(
        "verification_approved" if approve else "verification_rejected",
        user.email,
        {"user_name": user.get_short_name(), "reason": doc.rejection_reason},
    ))
    return doc


def set_status(user, status):
    """Staff shortcut on the user page: set the badge status directly."""
    agent, agency = _targets(user)
    for target in (agent, agency):
        if target:
            target.verification_status = status
            target.save(update_fields=["verification_status"])
