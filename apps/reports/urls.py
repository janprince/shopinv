from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("sales/", views.sales, name="sales"),
    path("sales/export/", views.sales_export, name="sales_export"),
    path("products/", views.products, name="products"),
    path("products/export/", views.products_export, name="products_export"),
    path("categories/", views.categories, name="categories"),
    path("categories/export/", views.categories_export, name="categories_export"),
    path("payments/", views.payments, name="payments"),
    path("payments/export/", views.payments_export, name="payments_export"),
    path("inventory/", views.inventory, name="inventory"),
    path("inventory/export/", views.inventory_export, name="inventory_export"),
    path("expiry/", views.expiry, name="expiry"),
    path("expiry/export/", views.expiry_export, name="expiry_export"),
    path("adjustments/", views.adjustments, name="adjustments"),
    path("adjustments/export/", views.adjustments_export, name="adjustments_export"),
    path("profit/", views.profit, name="profit"),
    path("profit/export/", views.profit_export, name="profit_export"),
]
