from django.contrib import admin

from .models import StockBatch, StockMovement


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = [
        "product",
        "batch_number",
        "quantity_remaining",
        "unit_cost",
        "expiry_date",
        "received_at",
    ]
    list_filter = ["source", "supplier", "expiry_date"]
    search_fields = ["product__name", "product__sku", "batch_number"]
    readonly_fields = ["quantity_remaining", "created_at"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["created_at", "product", "movement_type", "quantity", "quantity_after", "user"]
    list_filter = ["movement_type", "created_at"]
    search_fields = ["product__name", "product__sku", "reason"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
