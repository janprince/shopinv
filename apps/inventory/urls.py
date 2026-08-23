from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("receive/", views.receive, name="receive"),
    path("adjust/", views.adjust, name="adjust"),
    path("movements/", views.movements, name="movements"),
    path("movements/export/", views.movements_export, name="movements_export"),
    path("expiring/", views.expiring, name="expiring"),
    path("batch-options/", views.batch_options, name="batch_options"),
]
