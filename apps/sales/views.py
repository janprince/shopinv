from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.catalog.models import Category, Product
from apps.core.audit import AuditAction, record
from apps.core.permissions import owner_required
from apps.core.utils import csv_response, page_range, range_bounds, resolve_period
from apps.inventory.services import InsufficientStock, StockError

from .forms import ReverseSaleForm, SaleForm
from .models import PaymentMethod, Sale, SaleStatus
from .services import SaleError, complete_sale, reverse_sale

PAGE_SIZE = 15
SEARCH_LIMIT = 24


# --------------------------------------------------------------------------------------
# Point of sale
# --------------------------------------------------------------------------------------
def _pos_context(request, form=None, cart_json: str = "[]"):
    quick_picks = (
        Product.objects.active()
        .select_related("category")
        .filter(stock_quantity__gt=0)
        .annotate(
            sold=Coalesce(
                Sum("sale_items__quantity", filter=Q(sale_items__sale__status="completed")),
                Decimal("0"),
            )
        )
        .order_by("-sold", "name")[:8]
    )
    return {
        "form": form or SaleForm(initial={"idempotency_key": SaleForm.fresh_key()}),
        "cart_json": cart_json,
        "quick_picks": quick_picks,
        "payment_methods": PaymentMethod.choices,
        "categories": Category.objects.active(),
    }


@login_required
def pos(request):
    if request.method != "POST":
        return render(request, "sales/pos.html", _pos_context(request))

    form = SaleForm(request.POST)
    cart_json = request.POST.get("cart") or "[]"

    if not form.is_valid():
        for error in form.errors.get("cart", []):
            messages.error(request, error)
        return render(request, "sales/pos.html", _pos_context(request, form, cart_json))

    data = form.cleaned_data
    try:
        sale, created = complete_sale(
            raw_lines=data["cart"],
            user=request.user,
            payment_method=data["payment_method"],
            amount_received=data.get("amount_received"),
            discount=data.get("discount") or Decimal("0"),
            payment_reference=data.get("payment_reference", ""),
            notes=data.get("notes", ""),
            idempotency_key=str(data["idempotency_key"]),
        )
    except InsufficientStock as exc:
        messages.error(
            request,
            f"{exc} The sale was not recorded — change the quantity and try again.",
        )
        return render(request, "sales/pos.html", _pos_context(request, form, cart_json))
    except (SaleError, StockError) as exc:
        messages.error(request, str(exc))
        return render(request, "sales/pos.html", _pos_context(request, form, cart_json))

    if not created:
        messages.info(
            request,
            f"This sale was already recorded as {sale.sale_number}. Nothing was charged twice.",
        )
    return redirect("sales:complete", pk=sale.pk)


@login_required
def product_search(request):
    """HTMX partial for the till's search box."""
    term = (request.GET.get("q") or "").strip()
    category = request.GET.get("category")

    queryset = Product.objects.active().select_related("category")
    if category and category.isdigit():
        queryset = queryset.filter(category_id=int(category))

    exact_barcode = None
    if term:
        exact_barcode = queryset.filter(barcode__iexact=term).first()
        queryset = queryset.search(term)
    else:
        queryset = queryset.filter(stock_quantity__gt=0).order_by("name")

    products = list(queryset.order_by("-stock_quantity", "name")[:SEARCH_LIMIT])

    return render(
        request,
        "sales/partials/search_results.html",
        {
            "products": products,
            "term": term,
            "exact_barcode": exact_barcode,
            "truncated": len(products) == SEARCH_LIMIT,
        },
    )


@login_required
def stock_check(request):
    """Small JSON endpoint the till uses to re-check stock before submitting."""
    ids = [int(v) for v in request.GET.getlist("id") if v.isdigit()][:200]
    rows = Product.objects.filter(pk__in=ids).values(
        "id", "stock_quantity", "selling_price", "is_active"
    )
    return JsonResponse(
        {
            "products": {
                str(row["id"]): {
                    "stock": str(row["stock_quantity"]),
                    "price": str(row["selling_price"]),
                    "active": row["is_active"],
                }
                for row in rows
            },
            "server_time": timezone.localtime().isoformat(),
        }
    )


@login_required
def complete(request, pk: int):
    sale = get_object_or_404(Sale.objects.select_related("user").prefetch_related("items"), pk=pk)
    return render(request, "sales/complete.html", {"sale": sale})


# --------------------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------------------
def _filtered_sales(request):
    start, end, period = resolve_period(request, default_days=30)
    start_dt, end_dt = range_bounds(start, end)

    queryset = (
        Sale.objects.select_related("user", "reversed_by")
        .filter(completed_at__gte=start_dt, completed_at__lt=end_dt)
        .annotate(line_count=Count("items"))
        .order_by("-completed_at", "-id")
    )

    number = (request.GET.get("q") or "").strip()
    if number:
        queryset = queryset.filter(
            Q(sale_number__icontains=number)
            | Q(items__product_name__icontains=number)
            | Q(items__sku__icontains=number)
        ).distinct()

    payment = request.GET.get("payment")
    if payment in PaymentMethod.values:
        queryset = queryset.filter(payment_method=payment)

    status = request.GET.get("status")
    if status in SaleStatus.values:
        queryset = queryset.filter(status=status)

    user_id = request.GET.get("user")
    if user_id and user_id.isdigit():
        queryset = queryset.filter(user_id=int(user_id))

    return queryset, start, end, period


@login_required
def history(request):
    queryset, start, end, period = _filtered_sales(request)
    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    totals = queryset.filter(status=SaleStatus.COMPLETED).aggregate(
        revenue=Coalesce(Sum("total"), Decimal("0")),
        profit=Coalesce(Sum("gross_profit"), Decimal("0")),
        count=Count("id"),
    )

    return render(
        request,
        "sales/history.html",
        {
            "page_obj": page_obj,
            "page_numbers": page_range(page_obj),
            "sales": page_obj.object_list,
            "totals": totals,
            "start": start,
            "end": end,
            "period": period,
            "staff": get_user_model().objects.order_by("first_name", "username"),
            "payment_methods": PaymentMethod.choices,
            "statuses": SaleStatus.choices,
            "item_label": "sales",
        },
    )


@login_required
def history_export(request):
    queryset, *_ = _filtered_sales(request)
    is_owner = request.user.is_owner
    record(
        AuditAction.DATA_EXPORTED,
        request=request,
        summary="Exported sales history to CSV",
        details={"filters": dict(request.GET.items())},
    )

    header = [
        "Sale number",
        "Date & time",
        "Status",
        "Items",
        "Subtotal",
        "Discount",
        "Total",
        "Payment method",
        "Reference",
        "Recorded by",
    ]
    if is_owner:
        header += ["Cost of goods", "Estimated gross profit"]

    def rows():
        for sale in queryset.iterator(chunk_size=200):
            row = [
                sale.sale_number,
                timezone.localtime(sale.completed_at).strftime("%Y-%m-%d %H:%M"),
                sale.get_status_display(),
                sale.line_count,
                f"{sale.subtotal:.2f}",
                f"{sale.discount:.2f}",
                f"{sale.total:.2f}",
                sale.get_payment_method_display(),
                sale.payment_reference,
                sale.user.display_name if sale.user_id else "",
            ]
            if is_owner:
                row += [f"{sale.cost_total:.2f}", f"{sale.gross_profit:.2f}"]
            yield row

    return csv_response("sales", header, rows())


@login_required
def detail(request, pk: int):
    sale = get_object_or_404(
        Sale.objects.select_related("user", "reversed_by").prefetch_related("items__product"), pk=pk
    )
    movements = sale.movements.select_related("product", "batch", "user").order_by("id")
    return render(
        request,
        "sales/detail.html",
        {"sale": sale, "movements": movements, "reverse_form": ReverseSaleForm()},
    )


@login_required
def receipt(request, pk: int):
    sale = get_object_or_404(Sale.objects.select_related("user").prefetch_related("items"), pk=pk)
    return render(
        request,
        "sales/receipt.html",
        {"sale": sale, "auto_print": request.GET.get("print") == "1"},
    )


@owner_required
@require_http_methods(["GET", "POST"])
def reverse(request, pk: int):
    """Reversing moves money and stock, so it is owner-only and always explained."""
    sale = get_object_or_404(Sale, pk=pk)

    if sale.is_reversed:
        messages.info(request, f"Sale {sale.sale_number} was already reversed.")
        return redirect(sale.get_absolute_url())

    form = ReverseSaleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            reverse_sale(sale=sale, user=request.user, reason=form.cleaned_data["reason"])
        except (SaleError, StockError) as exc:
            messages.error(request, str(exc))
            return redirect(sale.get_absolute_url())
        messages.success(
            request,
            f"Sale {sale.sale_number} has been reversed and the items are back in stock.",
        )
        return redirect(sale.get_absolute_url())

    return render(request, "sales/reverse.html", {"sale": sale, "form": form})
