"""Read-only aggregations shared by the dashboard and the reports screens.

Everything here reads from snapshots stored on the sale lines, never from a
product's current price, so a report about last month never changes.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, F, Sum, Value, When
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.utils import range_bounds
from apps.inventory.models import DECREASE_TYPES, MovementType, StockBatch, StockMovement
from apps.sales.models import PaymentMethod, Sale, SaleItem, SaleStatus

ZERO = Decimal("0")
MONEY = DecimalField(max_digits=14, decimal_places=2)
QTY = DecimalField(max_digits=14, decimal_places=3)


def _money(expression):
    return Coalesce(expression, Value(ZERO), output_field=MONEY)


def _qty(expression):
    return Coalesce(expression, Value(ZERO), output_field=QTY)


def completed_sales(start: date, end: date):
    start_dt, end_dt = range_bounds(start, end)
    return Sale.objects.filter(
        status=SaleStatus.COMPLETED, completed_at__gte=start_dt, completed_at__lt=end_dt
    )


def completed_items(start: date, end: date):
    start_dt, end_dt = range_bounds(start, end)
    return SaleItem.objects.filter(
        sale__status=SaleStatus.COMPLETED,
        sale__completed_at__gte=start_dt,
        sale__completed_at__lt=end_dt,
    )


# --------------------------------------------------------------------------------------
# Headline numbers
# --------------------------------------------------------------------------------------
def sales_summary(start: date, end: date) -> dict:
    sales = completed_sales(start, end).aggregate(
        revenue=_money(Sum("total")),
        subtotal=_money(Sum("subtotal")),
        discount=_money(Sum("discount")),
        cost=_money(Sum("cost_total")),
        profit=_money(Sum("gross_profit")),
        count=Count("id"),
    )
    units = completed_items(start, end).aggregate(units=_qty(Sum("quantity")))["units"]
    sales["units"] = units
    sales["average_sale"] = (sales["revenue"] / sales["count"]) if sales["count"] else ZERO
    sales["margin_percent"] = (
        (sales["profit"] / sales["revenue"] * 100) if sales["revenue"] else None
    )
    return sales


def daily_series(start: date, end: date) -> list[dict]:
    """One row per calendar day, including days with no sales."""
    start_dt, end_dt = range_bounds(start, end)
    rows = (
        Sale.objects.filter(
            status=SaleStatus.COMPLETED, completed_at__gte=start_dt, completed_at__lt=end_dt
        )
        .annotate(day=TruncDate("completed_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(
            revenue=_money(Sum("total")),
            profit=_money(Sum("gross_profit")),
            count=Count("id"),
        )
        .order_by("day")
    )
    lookup = {row["day"]: row for row in rows}
    series = []
    cursor = start
    while cursor <= end:
        row = lookup.get(cursor)
        series.append(
            {
                "day": cursor,
                "revenue": row["revenue"] if row else ZERO,
                "profit": row["profit"] if row else ZERO,
                "count": row["count"] if row else 0,
            }
        )
        cursor += timedelta(days=1)
    return series


def payment_breakdown(start: date, end: date) -> list[dict]:
    rows = (
        completed_sales(start, end)
        .values("payment_method")
        .annotate(revenue=_money(Sum("total")), count=Count("id"))
        .order_by("-revenue")
    )
    labels = dict(PaymentMethod.choices)
    total = sum((row["revenue"] for row in rows), ZERO)
    return [
        {
            "method": row["payment_method"],
            "label": labels.get(row["payment_method"], row["payment_method"]),
            "revenue": row["revenue"],
            "count": row["count"],
            "share": (row["revenue"] / total * 100) if total else ZERO,
        }
        for row in rows
    ]


def sales_by_product(start: date, end: date, limit: int | None = None, order: str = "-revenue"):
    queryset = (
        completed_items(start, end)
        .values("product_id", "sku", "product_name", "unit", "product__category__name")
        .annotate(
            units=_qty(Sum("quantity")),
            revenue=_money(Sum("line_total")),
            cost=_money(Sum("line_cost")),
            profit=_money(Sum("gross_profit")),
            sale_count=Count("sale_id", distinct=True),
        )
        .order_by(order, "product_name")
    )
    return queryset[:limit] if limit else queryset


def sales_by_category(start: date, end: date):
    return (
        completed_items(start, end)
        .values("product__category__name")
        .annotate(
            units=_qty(Sum("quantity")),
            revenue=_money(Sum("line_total")),
            profit=_money(Sum("gross_profit")),
            product_count=Count("product_id", distinct=True),
        )
        .order_by("-revenue")
    )


def slow_movers(start: date, end: date, limit: int = 25):
    """Active products holding stock that sold little or nothing in the period."""
    sold = dict(
        completed_items(start, end)
        .values_list("product_id")
        .annotate(units=_qty(Sum("quantity")))
        .values_list("product_id", "units")
    )
    products = (
        Product.objects.active()
        .select_related("category")
        .filter(stock_quantity__gt=0)
        .with_stock_value()
    )
    rows = [{"product": product, "units": sold.get(product.pk, ZERO)} for product in products]
    rows.sort(key=lambda row: (row["units"], -row["product"].stock_value))
    return rows[:limit]


# --------------------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------------------
def inventory_value() -> dict:
    batch_totals = StockBatch.objects.filter(quantity_remaining__gt=0).aggregate(
        cost_value=_money(Sum(F("quantity_remaining") * F("unit_cost"))),
        units=_qty(Sum("quantity_remaining")),
    )
    retail = Product.objects.active().aggregate(
        retail_value=_money(Sum(F("stock_quantity") * F("selling_price")))
    )["retail_value"]
    return {
        "cost_value": batch_totals["cost_value"],
        "units": batch_totals["units"],
        "retail_value": retail,
        "potential_profit": retail - batch_totals["cost_value"],
        "product_count": Product.objects.active().filter(stock_quantity__gt=0).count(),
    }


def low_stock_products(limit: int | None = None):
    queryset = (
        Product.objects.active()
        .select_related("category")
        .needs_restock()
        .order_by("stock_quantity", "name")
    )
    return queryset[:limit] if limit else queryset


def out_of_stock_products(limit: int | None = None):
    queryset = Product.objects.active().select_related("category").out_of_stock().order_by("name")
    return queryset[:limit] if limit else queryset


def expiring_batches(warning_days: int, limit: int | None = None):
    today = timezone.localdate()
    horizon = today + timedelta(days=warning_days)
    queryset = (
        StockBatch.objects.live()
        .select_related("product", "product__category", "supplier")
        .filter(expiry_date__gte=today, expiry_date__lte=horizon)
        .order_by("expiry_date")
    )
    return queryset[:limit] if limit else queryset


def expired_batches(limit: int | None = None):
    queryset = (
        StockBatch.objects.expired()
        .select_related("product", "product__category", "supplier")
        .order_by("expiry_date")
    )
    return queryset[:limit] if limit else queryset


def adjustment_summary(start: date, end: date):
    start_dt, end_dt = range_bounds(start, end)
    adjustment_types = [
        MovementType.DAMAGED,
        MovementType.EXPIRED,
        MovementType.MISSING,
        MovementType.RETURN,
        MovementType.CORRECTION_UP,
        MovementType.CORRECTION_DOWN,
    ]
    rows = (
        StockMovement.objects.filter(
            created_at__gte=start_dt, created_at__lt=end_dt, movement_type__in=adjustment_types
        )
        .values("movement_type")
        .annotate(
            units=_qty(
                Sum(
                    Case(
                        When(quantity__lt=0, then=-F("quantity")),
                        default=F("quantity"),
                        output_field=QTY,
                    )
                )
            ),
            value=_money(
                Sum(
                    Case(
                        When(quantity__lt=0, then=-F("quantity") * F("unit_cost")),
                        default=F("quantity") * F("unit_cost"),
                        output_field=MONEY,
                    )
                )
            ),
            count=Count("id"),
        )
        .order_by("-value")
    )
    labels = dict(MovementType.choices)
    return [
        {
            "type": row["movement_type"],
            "label": labels.get(row["movement_type"], row["movement_type"]),
            "is_loss": row["movement_type"] in {t.value for t in DECREASE_TYPES},
            "units": row["units"],
            "value": row["value"],
            "count": row["count"],
        }
        for row in rows
    ]


def stock_losses(start: date, end: date):
    """Cost value of everything written off in the period."""
    start_dt, end_dt = range_bounds(start, end)
    loss_types = [
        MovementType.DAMAGED,
        MovementType.EXPIRED,
        MovementType.MISSING,
        MovementType.CORRECTION_DOWN,
    ]
    return StockMovement.objects.filter(
        created_at__gte=start_dt, created_at__lt=end_dt, movement_type__in=loss_types
    ).aggregate(value=_money(Sum(-F("quantity") * F("unit_cost"))))["value"]


# --------------------------------------------------------------------------------------
# Dashboard bundle — one call, a handful of queries
# --------------------------------------------------------------------------------------
def dashboard_metrics(*, warning_days: int, for_owner: bool) -> dict:
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    yesterday = today - timedelta(days=1)

    metrics = {
        "today": sales_summary(today, today),
        "yesterday": sales_summary(yesterday, yesterday),
        "week": sales_summary(week_start, today),
        "month": sales_summary(month_start, today),
        "low_stock": low_stock_products(limit=5),
        "low_stock_count": Product.objects.active().needs_restock().count(),
        "out_of_stock_count": Product.objects.active().out_of_stock().count(),
        "expiring": expiring_batches(warning_days, limit=5),
        "expiring_count": expiring_batches(warning_days).count(),
        "expired_count": StockBatch.objects.expired().count(),
        "recent_sales": (
            Sale.objects.select_related("user")
            .annotate(line_count=Count("items"))
            .order_by("-completed_at")[:5]
        ),
        "recent_movements": (StockMovement.objects.with_related().order_by("-created_at")[:5]),
    }

    change = None
    if metrics["yesterday"]["revenue"]:
        change = (
            (metrics["today"]["revenue"] - metrics["yesterday"]["revenue"])
            / metrics["yesterday"]["revenue"]
            * 100
        )
    metrics["today_change"] = change

    if for_owner:
        metrics["inventory"] = inventory_value()
        metrics["payments"] = payment_breakdown(month_start, today)
        metrics["best_sellers"] = list(sales_by_product(month_start, today, limit=5))
    return metrics
