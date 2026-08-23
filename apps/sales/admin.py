from django.contrib import admin

from .models import Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in SaleItem._meta.fields]


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ["sale_number", "completed_at", "status", "total", "payment_method", "user"]
    list_filter = ["status", "payment_method", "completed_at"]
    search_fields = ["sale_number"]
    date_hierarchy = "completed_at"
    inlines = [SaleItemInline]
    readonly_fields = [f.name for f in Sale._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
