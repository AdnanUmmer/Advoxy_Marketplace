from django.contrib import admin

from .models import FeaturedPlacement, Plan, Purchase, Subscription, WebhookEvent


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["name", "audience", "price_monthly", "listing_limit", "seats", "is_active"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "plan", "status", "current_period_end", "cancel_at_period_end"]
    list_filter = ["status", "plan"]


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["user", "kind", "amount", "currency", "status", "paid_at"]
    list_filter = ["kind", "status"]


admin.site.register(FeaturedPlacement)
admin.site.register(WebhookEvent)
