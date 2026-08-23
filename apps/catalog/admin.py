from django.contrib import admin

from .models import Category, Product, Supplier


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "created_at"]
    search_fields = ["name"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "location", "is_active"]
    search_fields = ["name", "phone", "location"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "category", "selling_price", "stock_quantity", "is_active"]
    list_filter = ["category", "is_active", "unit"]
    search_fields = ["name", "sku", "barcode"]
    #: Stock is only ever changed through a movement — never by typing a number here.
    readonly_fields = ["stock_quantity", "created_at", "updated_at"]
