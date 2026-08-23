from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.audit import AuditAction, record
from apps.core.utils import csv_response, page_range, range_bounds, resolve_period

from .forms import AdjustStockForm, MovementFilterForm, ReceiveStockForm
from .models import ADJUSTMENT_HELP, INCREASE_TYPES, MovementType, StockBatch, StockMovement
from .services import StockError, adjust_stock, receive_stock

PAGE_SIZE = 40


# --------------------------------------------------------------------------------------
# Receiving
# --------------------------------------------------------------------------------------
@login_required
def receive(request):
    """Two steps on purpose: fill in, then look at what you are about to record."""
    initial = {"received_on": timezone.localdate()}
    if request.GET.get("product"):
        initial["product"] = request.GET["product"]
    if request.GET.get("supplier"):
        initial["supplier"] = request.GET["supplier"]

    if request.method != "POST":
        return render(
            request,
            "inventory/receive.html",
            {"form": ReceiveStockForm(initial=initial), "stage": "form"},
        )

    form = ReceiveStockForm(request.POST)
    stage = request.POST.get("stage", "")

    if not form.is_valid() or stage == "edit":
        return render(request, "inventory/receive.html", {"form": form, "stage": "form"})

    data = form.cleaned_data
    if stage != "confirm":
        data = dict(data)
        data["total_cost"] = data["quantity"] * data["unit_cost"]
        data["stock_after"] = data["product"].stock_quantity + data["quantity"]
        return render(
            request,
            "inventory/receive.html",
            {"form": form, "stage": "review", "data": data},
        )
    data = form.cleaned_data

    received_on = data.get("received_on")
    received_at = None
    if received_on and received_on != timezone.localdate():
        received_at = timezone.make_aware(
            timezone.datetime.combine(received_on, timezone.datetime.min.time().replace(hour=12))
        )

    try:
        batch = receive_stock(
            product=data["product"],
            quantity=data["quantity"],
            unit_cost=data["unit_cost"],
            user=request.user,
            supplier=data.get("supplier"),
            batch_number=data.get("batch_number", ""),
            expiry_date=data.get("expiry_date"),
            notes=data.get("notes", ""),
            received_at=received_at,
            update_cost_price=data.get("update_cost_price", True),
        )
    except StockError as exc:
        messages.error(request, str(exc))
        return render(request, "inventory/receive.html", {"form": form, "stage": "form"})

    product = batch.product
    product.refresh_from_db()
    messages.success(
        request,
        f"Stock received: {product.format_quantity(batch.quantity_received)} of {product.name}. "
        f"There is now {product.display_stock} on hand.",
    )
    if "save_and_add" in request.POST:
        return redirect("inventory:receive")
    return redirect(product.get_absolute_url())


# --------------------------------------------------------------------------------------
# Adjustments
# --------------------------------------------------------------------------------------
@login_required
def adjust(request):
    initial = {}
    if request.GET.get("product"):
        initial["product"] = request.GET["product"]
    if request.GET.get("type"):
        initial["movement_type"] = request.GET["type"]

    if request.method != "POST":
        form = AdjustStockForm(initial=initial)
        return render(
            request,
            "inventory/adjust.html",
            {"form": form, "stage": "form", "help_by_type": ADJUSTMENT_HELP},
        )

    form = AdjustStockForm(request.POST)
    stage = request.POST.get("stage", "")

    if not form.is_valid() or stage == "edit":
        return render(
            request,
            "inventory/adjust.html",
            {"form": form, "stage": "form", "help_by_type": ADJUSTMENT_HELP},
        )

    data = form.cleaned_data
    product = data["product"]
    movement_type = data["movement_type"]
    is_increase = movement_type in INCREASE_TYPES
    delta = data["quantity"] if is_increase else -data["quantity"]
    expected_after = product.stock_quantity + delta
    is_large = data["quantity"] >= request.shop.large_adjustment_threshold

    if stage != "confirm":
        return render(
            request,
            "inventory/adjust.html",
            {
                "form": form,
                "stage": "review",
                "data": data,
                "is_increase": is_increase,
                "expected_after": expected_after,
                "is_large": is_large,
                "type_label": MovementType(movement_type).label,
                "help_by_type": ADJUSTMENT_HELP,
            },
        )

    try:
        adjust_stock(
            product=product,
            movement_type=movement_type,
            quantity=data["quantity"],
            reason=data["reason"],
            user=request.user,
            batch=data.get("batch"),
            notes=data.get("notes", ""),
        )
    except StockError as exc:
        messages.error(request, str(exc))
        return render(
            request,
            "inventory/adjust.html",
            {"form": form, "stage": "form", "help_by_type": ADJUSTMENT_HELP},
        )

    product.refresh_from_db()
    messages.success(
        request,
        f"{MovementType(movement_type).label} recorded for {product.name}. "
        f"There is now {product.display_stock} on hand.",
    )
    if "save_and_add" in request.POST:
        return redirect("inventory:adjust")
    return redirect(product.get_absolute_url())


# --------------------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------------------
def _filtered_movements(request):
    start, end, period = resolve_period(request, default_days=30)
    start_dt, end_dt = range_bounds(start, end)

    queryset = (
        StockMovement.objects.with_related()
        .filter(created_at__gte=start_dt, created_at__lt=end_dt)
        .order_by("-created_at", "-id")
    )

    filters = MovementFilterForm(request.GET or None)
    filters.is_valid()
    cleaned = filters.cleaned_data if filters.is_bound else {}

    if cleaned.get("product"):
        queryset = queryset.filter(product=cleaned["product"])
    if cleaned.get("category"):
        queryset = queryset.filter(product__category=cleaned["category"])
    if cleaned.get("movement_type"):
        queryset = queryset.filter(movement_type=cleaned["movement_type"])
    if cleaned.get("supplier"):
        queryset = queryset.filter(batch__supplier=cleaned["supplier"])

    user_id = request.GET.get("user")
    if user_id and user_id.isdigit():
        queryset = queryset.filter(user_id=int(user_id))

    term = (request.GET.get("q") or "").strip()
    if term:
        queryset = queryset.filter(
            Q(product__name__icontains=term)
            | Q(product__sku__icontains=term)
            | Q(reason__icontains=term)
            | Q(sale__sale_number__icontains=term)
        )

    return queryset, filters, start, end, period


@login_required
def movements(request):
    from django.contrib.auth import get_user_model

    queryset, filters, start, end, period = _filtered_movements(request)
    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "inventory/movements.html",
        {
            "page_obj": page_obj,
            "page_numbers": page_range(page_obj),
            "movements": page_obj.object_list,
            "filters": filters,
            "start": start,
            "end": end,
            "period": period,
            "staff": get_user_model().objects.order_by("first_name", "username"),
            "selected_user": request.GET.get("user", ""),
            "term": request.GET.get("q", ""),
            "item_label": "stock changes",
        },
    )


@login_required
def movements_export(request):
    queryset, *_ = _filtered_movements(request)
    record(
        AuditAction.DATA_EXPORTED,
        request=request,
        summary="Exported the stock movement ledger to CSV",
        details={"filters": dict(request.GET.items())},
    )

    def rows():
        for movement in queryset.iterator(chunk_size=200):
            yield [
                timezone.localtime(movement.created_at).strftime("%Y-%m-%d %H:%M"),
                movement.product.sku,
                movement.product.name,
                movement.product.category.name if movement.product.category_id else "",
                movement.get_movement_type_display(),
                movement.direction_label,
                f"{abs(movement.quantity):f}".rstrip("0").rstrip("."),
                f"{movement.quantity_before:f}".rstrip("0").rstrip("."),
                f"{movement.quantity_after:f}".rstrip("0").rstrip("."),
                movement.reason,
                movement.sale.sale_number if movement.sale_id else "",
                movement.batch.batch_number if movement.batch_id else "",
                movement.user.display_name if movement.user_id else "",
            ]

    return csv_response(
        "stock-movements",
        [
            "Date & time",
            "SKU",
            "Product",
            "Category",
            "Change type",
            "Direction",
            "Quantity",
            "Stock before",
            "Stock after",
            "Reason",
            "Sale",
            "Batch",
            "Recorded by",
        ],
        rows(),
    )


@login_required
def batch_options(request):
    """HTMX partial: the batch picker for the chosen product."""
    product_id = request.GET.get("product")
    batches = StockBatch.objects.none()
    product = None
    if product_id and product_id.isdigit():
        product = Product.objects.filter(pk=int(product_id)).first()
        batches = (
            StockBatch.objects.filter(product_id=int(product_id), quantity_remaining__gt=0)
            .select_related("supplier")
            .fefo()
        )
    return render(
        request,
        "inventory/partials/batch_options.html",
        {"batches": batches, "product": product},
    )


@login_required
def expiring(request):
    """Everything that needs attention before it goes off."""
    warning_days = request.shop.expiry_warning_days
    today = timezone.localdate()
    horizon = today + timedelta(days=warning_days)

    expired_batches = (
        StockBatch.objects.select_related("product", "product__category", "supplier")
        .expired(today)
        .order_by("expiry_date")
    )
    soon_batches = (
        StockBatch.objects.select_related("product", "product__category", "supplier")
        .live()
        .filter(expiry_date__gte=today, expiry_date__lte=horizon)
        .order_by("expiry_date")
    )
    return render(
        request,
        "inventory/expiring.html",
        {
            "expired_batches": expired_batches,
            "soon_batches": soon_batches,
            "warning_days": warning_days,
            "today": today,
        },
    )
