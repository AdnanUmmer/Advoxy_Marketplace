from django.contrib import admin

from .models import Inquiry, Message, Thread


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = ["pk", "listing", "buyer", "owner", "last_message_at"]
    inlines = [MessageInline]


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "listing", "created_at"]
