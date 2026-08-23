"""Django admin is a support/repair tool only — day-to-day work happens in the app.

Everything here is read-only where the data must stay trustworthy.
"""

from django.contrib import admin

from .models import AuditEvent, ShopSettings


@admin.register(ShopSettings)
class ShopSettingsAdmin(admin.ModelAdmin):
    list_display = ["shop_name", "expiry_warning_days", "updated_at"]

    def has_add_permission(self, request):
        return not ShopSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor_label", "action", "summary"]
    list_filter = ["action", "created_at"]
    search_fields = ["summary", "actor_label", "object_label"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
