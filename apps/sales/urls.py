from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("new/", views.pos, name="pos"),
    path("new/search/", views.product_search, name="product_search"),
    path("new/stock-check/", views.stock_check, name="stock_check"),
    path("history/", views.history, name="history"),
    path("history/export/", views.history_export, name="history_export"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/done/", views.complete, name="complete"),
    path("<int:pk>/receipt/", views.receipt, name="receipt"),
    path("<int:pk>/reverse/", views.reverse, name="reverse"),
]
