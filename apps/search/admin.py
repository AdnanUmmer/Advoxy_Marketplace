from django.contrib import admin

from .models import Favorite, SavedSearch

admin.site.register(Favorite)


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "email_alerts", "last_notified_at", "created_at"]
