from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dashboard/", views.dashboard, name="dashboard_alt"),
    path("settings/", views.shop_settings, name="settings"),
    path("audit/", views.audit_log, name="audit_log"),
    path("audit/export/", views.audit_export, name="audit_export"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
    path("healthz/", views.healthz, name="healthz"),
]
