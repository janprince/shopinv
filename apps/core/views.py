from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.response import TemplateResponse
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import requires_csrf_token

from apps.reports.services import dashboard_metrics

from .audit import changed_fields, record, snapshot
from .forms import ShopSettingsForm
from .models import AuditAction as Actions
from .models import AuditEvent, ShopSettings
from .permissions import owner_required
from .utils import page_range, resolve_period


@login_required
def dashboard(request):
    metrics = dashboard_metrics(
        warning_days=request.shop.expiry_warning_days,
        for_owner=request.user.is_owner,
    )
    return render(
        request,
        "core/dashboard.html",
        {"m": metrics, "today": timezone.localdate()},
    )


# --------------------------------------------------------------------------------------
# Shop settings — owner only
# --------------------------------------------------------------------------------------
@owner_required
def shop_settings(request):
    settings_obj = ShopSettings.load()
    tracked = list(ShopSettingsForm.Meta.fields)
    before = snapshot(settings_obj, tracked)
    form = ShopSettingsForm(request.POST or None, instance=settings_obj)

    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.updated_by = request.user
        saved.save()
        diff = changed_fields(before, snapshot(saved, tracked))
        if diff:
            record(
                Actions.SETTINGS_UPDATED,
                request=request,
                obj=saved,
                summary="Shop settings were updated",
                details={"changes": diff},
            )
        messages.success(request, "Shop settings have been saved.")
        return redirect("core:settings")

    return render(request, "core/settings.html", {"form": form, "object": settings_obj})


# --------------------------------------------------------------------------------------
# Audit history — owner only
# --------------------------------------------------------------------------------------
@owner_required
def audit_log(request):
    from django.contrib.auth import get_user_model

    from .utils import range_bounds

    start, end, period = resolve_period(request, default_days=30)
    start_dt, end_dt = range_bounds(start, end)

    events = (
        AuditEvent.objects.select_related("actor")
        .filter(created_at__gte=start_dt, created_at__lt=end_dt)
        .order_by("-created_at", "-id")
    )

    action = request.GET.get("action")
    if action in Actions.values:
        events = events.filter(action=action)

    actor = request.GET.get("actor")
    if actor and actor.isdigit():
        events = events.filter(actor_id=int(actor))

    term = (request.GET.get("q") or "").strip()
    if term:
        events = events.filter(summary__icontains=term)

    paginator = Paginator(events, 40)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "core/audit_log.html",
        {
            "page_obj": page_obj,
            "page_numbers": page_range(page_obj),
            "events": page_obj.object_list,
            "actions": Actions.choices,
            "staff": get_user_model().objects.order_by("first_name", "username"),
            "start": start,
            "end": end,
            "period": period,
            "term": term,
            "item_label": "recorded actions",
        },
    )


@owner_required
def audit_export(request):
    from .utils import csv_response, range_bounds

    start, end, _period = resolve_period(request, default_days=30)
    start_dt, end_dt = range_bounds(start, end)
    events = (
        AuditEvent.objects.select_related("actor")
        .filter(created_at__gte=start_dt, created_at__lt=end_dt)
        .order_by("-created_at")
    )
    record(
        Actions.DATA_EXPORTED,
        request=request,
        summary="Exported the audit history to CSV",
        details={"from": str(start), "to": str(end)},
    )

    def rows():
        for event in events.iterator(chunk_size=200):
            yield [
                timezone.localtime(event.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                event.actor_label or "System",
                event.get_action_display(),
                event.summary,
                event.object_label,
                event.ip_address or "",
            ]

    return csv_response(
        "audit-history",
        ["Date & time", "Who", "Action", "What happened", "Record", "IP address"],
        rows(),
    )


# --------------------------------------------------------------------------------------
# PWA plumbing & health
# --------------------------------------------------------------------------------------
@cache_control(max_age=3600)
def manifest(request):
    shop = ShopSettings.load()
    return JsonResponse(
        {
            "name": f"{shop.shop_name} — Shop Manager",
            "short_name": shop.shop_name[:12],
            "description": "Inventory and sales for the shop.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "any",
            "background_color": "#fbf9f4",
            "theme_color": "#10301f",
            "icons": [
                {
                    "src": static("img/favicon.svg"),
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        }
    )


@cache_control(max_age=0, no_cache=True)
def service_worker(request):
    """Served from the site root so its scope covers the whole app."""
    response = TemplateResponse(request, "core/sw.js", content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    return render(request, "core/offline.html")


def healthz(request):
    """Used by Render's health check."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "database unavailable"}, status=503)
    return JsonResponse({"status": "ok", "time": timezone.now().isoformat()})


# --------------------------------------------------------------------------------------
# Error pages — friendly, never technical
# --------------------------------------------------------------------------------------
@requires_csrf_token
def error_403(request, exception=None):
    return render(
        request,
        "core/error.html",
        {
            "code": "403",
            "title": "You do not have access to this page",
            "body": str(exception)
            if exception
            else "This part of the app is for the shop owner. Ask them if you need it.",
        },
        status=403,
    )


def error_404(request, exception=None):
    return render(
        request,
        "core/error.html",
        {
            "code": "404",
            "title": "That page could not be found",
            "body": "The link may be old, or the record may have been renamed.",
        },
        status=404,
    )


@requires_csrf_token
def error_500(request):
    return render(
        request,
        "core/error.html",
        {
            "code": "500",
            "title": "Something went wrong on our side",
            "body": "Nothing you did caused this. Please try again — if it keeps happening, "
            "tell the shop owner so it can be looked into.",
        },
        status=500,
    )
