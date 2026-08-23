from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.core.audit import AuditAction, record
from apps.core.permissions import owner_required
from apps.core.utils import csv_response, resolve_period

from . import services as svc

ZERO = Decimal("0")


def _period(request, default_days: int = 30):
    start, end, period = resolve_period(request, default_days=default_days)
    return {"start": start, "end": end, "period": period}


def _log_export(request, what: str, ctx: dict):
    record(
        AuditAction.DATA_EXPORTED,
        request=request,
        summary=f"Exported the {what} report to CSV",
        details={"from": str(ctx["start"]), "to": str(ctx["end"])},
    )


@login_required
def index(request):
    ctx = _period(request)
    today = timezone.localdate()
    return render(
        request,
        "reports/index.html",
        {
            **ctx,
            "summary": svc.sales_summary(ctx["start"], ctx["end"]),
            "today": svc.sales_summary(today, today),
            "inventory": svc.inventory_value(),
            "low_stock_count": svc.low_stock_products().count(),
            "out_of_stock_count": svc.out_of_stock_products().count(),
            "expiring_count": svc.expiring_batches(request.shop.expiry_warning_days).count(),
            "expired_count": svc.expired_batches().count(),
            "losses": svc.stock_losses(ctx["start"], ctx["end"]),
        },
    )


# --------------------------------------------------------------------------------------
# Sales over time
# --------------------------------------------------------------------------------------
@login_required
def sales(request):
    ctx = _period(request)
    series = svc.daily_series(ctx["start"], ctx["end"])
    grouping = request.GET.get("group", "day")

    rows = series
    if grouping in {"week", "month"}:
        buckets: dict = {}
        for row in series:
            key = (
                row["day"] - timedelta(days=row["day"].weekday())
                if grouping == "week"
                else row["day"].replace(day=1)
            )
            bucket = buckets.setdefault(
                key, {"day": key, "revenue": ZERO, "profit": ZERO, "count": 0}
            )
            bucket["revenue"] += row["revenue"]
            bucket["profit"] += row["profit"]
            bucket["count"] += row["count"]
        rows = sorted(buckets.values(), key=lambda item: item["day"])

    peak = max((row["revenue"] for row in rows), default=ZERO)
    return render(
        request,
        "reports/sales.html",
        {
            **ctx,
            "rows": rows,
            "grouping": grouping,
            "peak": peak,
            "summary": svc.sales_summary(ctx["start"], ctx["end"]),
            "payments": svc.payment_breakdown(ctx["start"], ctx["end"]),
        },
    )


@login_required
def sales_export(request):
    ctx = _period(request)
    _log_export(request, "sales", ctx)
    rows = svc.daily_series(ctx["start"], ctx["end"])
    is_owner = request.user.is_owner
    header = ["Date", "Sales", "Revenue"] + (["Estimated gross profit"] if is_owner else [])

    def generate():
        for row in rows:
            line = [row["day"].strftime("%Y-%m-%d"), row["count"], f"{row['revenue']:.2f}"]
            if is_owner:
                line.append(f"{row['profit']:.2f}")
            yield line

    return csv_response("daily-sales", header, generate())


# --------------------------------------------------------------------------------------
# Product performance
# --------------------------------------------------------------------------------------
@login_required
def products(request):
    ctx = _period(request)
    order = request.GET.get("order", "-revenue")
    if order not in {"-revenue", "-units", "-profit", "revenue", "units"}:
        order = "-revenue"
    rows = list(svc.sales_by_product(ctx["start"], ctx["end"], limit=100, order=order))
    peak = max((row["revenue"] for row in rows), default=ZERO)
    return render(
        request,
        "reports/products.html",
        {
            **ctx,
            "rows": rows,
            "order": order,
            "peak": peak,
            "slow": svc.slow_movers(ctx["start"], ctx["end"], limit=15),
        },
    )


@login_required
def products_export(request):
    ctx = _period(request)
    _log_export(request, "sales by product", ctx)
    rows = svc.sales_by_product(ctx["start"], ctx["end"])
    is_owner = request.user.is_owner
    header = ["SKU", "Product", "Category", "Units sold", "Revenue", "Sales"]
    if is_owner:
        header += ["Cost of goods", "Estimated gross profit"]

    def generate():
        for row in rows:
            line = [
                row["sku"],
                row["product_name"],
                row["product__category__name"] or "",
                f"{row['units']:f}".rstrip("0").rstrip("."),
                f"{row['revenue']:.2f}",
                row["sale_count"],
            ]
            if is_owner:
                line += [f"{row['cost']:.2f}", f"{row['profit']:.2f}"]
            yield line

    return csv_response("sales-by-product", header, generate())


@login_required
def categories(request):
    ctx = _period(request)
    rows = list(svc.sales_by_category(ctx["start"], ctx["end"]))
    total = sum((row["revenue"] for row in rows), ZERO)
    return render(request, "reports/categories.html", {**ctx, "rows": rows, "total": total})


@login_required
def categories_export(request):
    ctx = _period(request)
    _log_export(request, "sales by category", ctx)
    rows = svc.sales_by_category(ctx["start"], ctx["end"])

    def generate():
        for row in rows:
            yield [
                row["product__category__name"] or "Uncategorised",
                row["product_count"],
                f"{row['units']:f}".rstrip("0").rstrip("."),
                f"{row['revenue']:.2f}",
                f"{row['profit']:.2f}",
            ]

    return csv_response(
        "sales-by-category",
        ["Category", "Products sold", "Units", "Revenue", "Estimated gross profit"],
        generate(),
    )


@login_required
def payments(request):
    ctx = _period(request)
    rows = svc.payment_breakdown(ctx["start"], ctx["end"])
    return render(
        request,
        "reports/payments.html",
        {**ctx, "rows": rows, "summary": svc.sales_summary(ctx["start"], ctx["end"])},
    )


@login_required
def payments_export(request):
    ctx = _period(request)
    _log_export(request, "payment methods", ctx)
    rows = svc.payment_breakdown(ctx["start"], ctx["end"])
    return csv_response(
        "sales-by-payment-method",
        ["Payment method", "Sales", "Revenue", "Share of revenue %"],
        ([r["label"], r["count"], f"{r['revenue']:.2f}", f"{r['share']:.1f}"] for r in rows),
    )


# --------------------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------------------
@login_required
def inventory(request):
    return render(
        request,
        "reports/inventory.html",
        {
            "valuation": svc.inventory_value(),
            "low_stock": svc.low_stock_products(),
            "out_of_stock": svc.out_of_stock_products(),
        },
    )


@login_required
def inventory_export(request):
    from apps.catalog.models import Product

    record(
        AuditAction.DATA_EXPORTED,
        request=request,
        summary="Exported the inventory valuation to CSV",
    )
    products_qs = (
        Product.objects.active().select_related("category").with_stock_value().order_by("name")
    )

    def generate():
        for product in products_qs.iterator(chunk_size=200):
            yield [
                product.sku,
                product.name,
                product.category.name,
                f"{product.stock_quantity:f}".rstrip("0").rstrip("."),
                product.get_unit_display(),
                f"{product.stock_value:.2f}",
                f"{product.retail_stock_value:.2f}",
                product.stock_status_label,
            ]

    return csv_response(
        "inventory-valuation",
        [
            "SKU",
            "Product",
            "Category",
            "Stock on hand",
            "Unit",
            "Value at cost",
            "Value at selling price",
            "Stock status",
        ],
        generate(),
    )


@login_required
def expiry(request):
    warning_days = request.shop.expiry_warning_days
    return render(
        request,
        "reports/expiry.html",
        {
            "expiring": svc.expiring_batches(warning_days),
            "expired": svc.expired_batches(),
            "warning_days": warning_days,
            "today": timezone.localdate(),
        },
    )


@login_required
def expiry_export(request):
    warning_days = request.shop.expiry_warning_days
    record(AuditAction.DATA_EXPORTED, request=request, summary="Exported the expiry report to CSV")
    batches = list(svc.expired_batches()) + list(svc.expiring_batches(warning_days))

    def generate():
        for batch in batches:
            yield [
                batch.product.sku,
                batch.product.name,
                batch.batch_number,
                batch.supplier.name if batch.supplier_id else "",
                batch.expiry_date.strftime("%Y-%m-%d") if batch.expiry_date else "",
                batch.days_to_expiry,
                "Expired" if batch.is_expired else "Expiring soon",
                f"{batch.quantity_remaining:f}".rstrip("0").rstrip("."),
                f"{batch.remaining_value:.2f}",
            ]

    return csv_response(
        "expiry-report",
        [
            "SKU",
            "Product",
            "Batch",
            "Supplier",
            "Expiry date",
            "Days left",
            "Status",
            "Quantity remaining",
            "Value at cost",
        ],
        generate(),
    )


@login_required
def adjustments(request):
    ctx = _period(request)
    rows = svc.adjustment_summary(ctx["start"], ctx["end"])
    from apps.core.utils import range_bounds
    from apps.inventory.models import StockMovement

    start_dt, end_dt = range_bounds(ctx["start"], ctx["end"])
    detail = (
        StockMovement.objects.with_related()
        .filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt,
            movement_type__in=[
                "damaged",
                "expired",
                "missing",
                "return",
                "correction_up",
                "correction_down",
            ],
        )
        .order_by("-created_at")[:100]
    )
    return render(
        request,
        "reports/adjustments.html",
        {
            **ctx,
            "rows": rows,
            "detail": detail,
            "losses": svc.stock_losses(ctx["start"], ctx["end"]),
        },
    )


@login_required
def adjustments_export(request):
    ctx = _period(request)
    _log_export(request, "stock adjustments", ctx)
    from apps.core.utils import range_bounds
    from apps.inventory.models import StockMovement

    start_dt, end_dt = range_bounds(ctx["start"], ctx["end"])
    movements = (
        StockMovement.objects.with_related()
        .filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt,
            movement_type__in=[
                "damaged",
                "expired",
                "missing",
                "return",
                "correction_up",
                "correction_down",
            ],
        )
        .order_by("-created_at")
    )

    def generate():
        for movement in movements.iterator(chunk_size=200):
            yield [
                timezone.localtime(movement.created_at).strftime("%Y-%m-%d %H:%M"),
                movement.product.sku,
                movement.product.name,
                movement.get_movement_type_display(),
                movement.direction_label,
                f"{abs(movement.quantity):f}".rstrip("0").rstrip("."),
                f"{abs(movement.value_effect or 0):.2f}",
                movement.reason,
                movement.user.display_name if movement.user_id else "",
            ]

    return csv_response(
        "stock-adjustments",
        [
            "Date & time",
            "SKU",
            "Product",
            "Type",
            "Direction",
            "Quantity",
            "Value at cost",
            "Reason",
            "Recorded by",
        ],
        generate(),
    )


# --------------------------------------------------------------------------------------
# Profit — owner only, because it exposes cost prices
# --------------------------------------------------------------------------------------
@owner_required
def profit(request):
    ctx = _period(request)
    summary = svc.sales_summary(ctx["start"], ctx["end"])
    losses = svc.stock_losses(ctx["start"], ctx["end"])
    return render(
        request,
        "reports/profit.html",
        {
            **ctx,
            "summary": summary,
            "losses": losses,
            "after_losses": summary["profit"] - losses,
            "by_product": list(
                svc.sales_by_product(ctx["start"], ctx["end"], limit=20, order="-profit")
            ),
            # Ranked by profit, not revenue: this panel is about profit, and the
            # bars are scaled against the first row.
            "by_category": list(
                svc.sales_by_category(ctx["start"], ctx["end"]).order_by("-profit")
            ),
            "series": svc.daily_series(ctx["start"], ctx["end"]),
        },
    )


@owner_required
def profit_export(request):
    ctx = _period(request)
    _log_export(request, "gross profit", ctx)
    rows = svc.sales_by_product(ctx["start"], ctx["end"], order="-profit")

    def generate():
        for row in rows:
            margin = (row["profit"] / row["revenue"] * 100) if row["revenue"] else ZERO
            yield [
                row["sku"],
                row["product_name"],
                f"{row['units']:f}".rstrip("0").rstrip("."),
                f"{row['revenue']:.2f}",
                f"{row['cost']:.2f}",
                f"{row['profit']:.2f}",
                f"{margin:.1f}",
            ]

    return csv_response(
        "estimated-gross-profit",
        [
            "SKU",
            "Product",
            "Units sold",
            "Revenue",
            "Cost of goods sold",
            "Estimated gross profit",
            "Margin %",
        ],
        generate(),
    )
