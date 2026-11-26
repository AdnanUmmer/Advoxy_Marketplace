from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import verified_email_required
from apps.listings.models import Listing

from . import services
from .models import Message, Thread


class InquiryForm(forms.Form):
    name = forms.CharField(label=gettext_lazy("Name"), max_length=150)
    email = forms.EmailField(label=gettext_lazy("Email"))
    phone = forms.CharField(label=gettext_lazy("Phone"), max_length=32, required=False)
    message = forms.CharField(label=gettext_lazy("Message"), max_length=3000, widget=forms.Textarea(attrs={"rows": 4}))


def inquiry_form_for(user, listing):
    if not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    return InquiryForm(initial={
        "name": user.full_name,
        "email": user.email,
        "phone": profile.phone if profile else "",
        "message": _("Hello, I'm interested in “%(title)s”. Is it still available?") % {"title": listing.title},
    })


# ---------------------------------------------------------------------------
# Inquiry
# ---------------------------------------------------------------------------
@require_POST
@verified_email_required
def inquire(request, pk):
    listing = get_object_or_404(Listing.objects.published(), pk=pk)
    form = InquiryForm(request.POST)
    error = None
    if form.is_valid():
        try:
            inquiry = services.start_inquiry(listing, request.user, **form.cleaned_data)
        except services.MessagingError as exc:
            error = str(exc)
        else:
            if request.htmx:
                return render(request, "messaging/_inquiry_sent.html", {"thread": inquiry.thread, "listing": listing})
            messages.success(request, _("Message sent. Replies will appear in your inbox."))
            return redirect(inquiry.thread)
    if request.htmx:
        return render(request, "messaging/_inquiry_form.html", {"form": form, "listing": listing, "error": error})
    if error:
        messages.error(request, error)
    return redirect(listing.get_absolute_url() + "#contact")


# ---------------------------------------------------------------------------
# Inbox and conversations
# ---------------------------------------------------------------------------
def _threads(user):
    return (
        Thread.objects.for_user(user)
        .with_unread(user)
        .select_related("listing", "buyer", "owner")
        .prefetch_related("listing__photos")
    )


def _last_messages(threads):
    """{thread_id: last Message} in one query."""
    ids = [t.pk for t in threads]
    last = {}
    for m in Message.objects.filter(thread_id__in=ids).order_by("thread_id", "-created_at", "-id").distinct("thread_id"):
        last[m.thread_id] = m
    return last


def _inbox_context(user, active=None):
    threads = list(_threads(user))
    last = _last_messages(threads)
    for t in threads:
        t.last_message = last.get(t.pk)
        t.other_person = t.other(user)
    return {"threads": threads, "active": active}


@login_required
def inbox(request):
    return render(request, "messaging/inbox.html", _inbox_context(request.user))


@login_required
@require_GET
def thread_list(request):
    """Polled every 5 seconds to refresh previews and unread counts."""
    active_id = request.GET.get("active")
    ctx = _inbox_context(request.user)
    ctx["active_id"] = int(active_id) if active_id and active_id.isdigit() else None
    return render(request, "messaging/_thread_list.html", ctx)


def _get_thread(request, pk):
    thread = get_object_or_404(Thread.objects.select_related("listing", "buyer", "owner"), pk=pk)
    if not thread.is_participant(request.user):
        raise Http404
    return thread


@login_required
def thread(request, pk):
    convo = _get_thread(request, pk)
    services.mark_read(convo, request.user)
    msgs = list(convo.messages.select_related("sender"))
    ctx = _inbox_context(request.user, active=convo)
    ctx.update({
        "thread": convo,
        "other": convo.other(request.user),
        "messages_list": msgs,
        "last_id": msgs[-1].pk if msgs else 0,
        "is_owner": convo.owner_id == request.user.pk,
        "inquiries": list(convo.inquiries.all()[:3]) if convo.owner_id == request.user.pk else [],
    })
    return render(request, "messaging/thread.html", ctx)


@require_POST
@verified_email_required
def send(request, pk):
    convo = _get_thread(request, pk)
    try:
        msg = services.post_message(convo, request.user, request.POST.get("body", ""))
    except services.MessagingError as exc:
        if request.htmx:
            return HttpResponse(f'<p class="field-error" role="alert">{exc}</p>', status=422)
        messages.error(request, str(exc))
        return redirect(convo)
    if request.htmx:
        return render(request, "messaging/_messages.html", {"messages_list": [msg], "thread": convo, "last_id": msg.pk})
    return redirect(convo)


@login_required
@require_GET
def poll(request, pk):
    """Polled every 5 seconds: returns messages newer than ?after=<id> and a fresh poller."""
    convo = _get_thread(request, pk)
    after = request.GET.get("after", "0")
    after = int(after) if after.isdigit() else 0
    new = list(convo.messages.filter(pk__gt=after).select_related("sender"))
    if new:
        services.mark_read(convo, request.user)
    last_id = new[-1].pk if new else after
    return render(request, "messaging/_messages.html", {"messages_list": new, "thread": convo, "last_id": last_id, "poll": True})


@login_required
@require_GET
def unread_badge(request):
    return render(request, "messaging/_unread_badge.html", {"unread_count": services.unread_total(request.user)})
