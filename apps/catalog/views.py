from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Min, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.audit import AuditAction, changed_fields, record, snapshot
from apps.core.utils import csv_response, page_range
from apps.inventory.models import StockBatch
from apps.inventory.services import receive_stock

from .forms import CategoryForm, ProductForm, SupplierForm
from .models import Category, Product, Supplier

PAGE_SIZE = 25

SORT_FIELDS = {
    "name": "name",
    "-name": "-name",
    "sku": "sku",
    "-sku": "-sku",
    "stock": "stock_quantity",
    "-stock": "-stock_quantity",
    "price": "selling_price",
    "-price": "-selling_price",
    "category": "category__name",
    "-category": "-category__name",
    "updated": "updated_at",
    "-updated": "-updated_at",
}


def _filtered_products(request):
    """Shared by the HTML list and the CSV export so they can never disagree."""
    today = timezone.localdate()
    horizon = today + timedelta(days=request.shop.expiry_warning_days)

    queryset = Product.objects.select_related("category").with_stock_value()

    status = request.GET.get("status", "")
    if status == "inactive":
        queryset = queryset.filter(is_active=False)
    elif status != "all":
        queryset = queryset.filter(is_active=True)

    term = (request.GET.get("q") or "").strip()
    if term:
        queryset = queryset.search(term)

    category = request.GET.get("category")
    if category and category.isdigit():
        queryset = queryset.filter(category_id=int(category))

    stock = request.GET.get("stock")
    if stock == "in":
        queryset = queryset.filter(stock_quantity__gt=F("minimum_stock"))
    elif stock == "low":
        queryset = queryset.low_stock()
    elif stock == "out":
        queryset = queryset.out_of_stock()
    elif stock == "restock":
        queryset = queryset.needs_restock()

    expiry = request.GET.get("expiry")
    if expiry == "expiring":
        queryset = queryset.filter(
            pk__in=StockBatch.objects.filter(
                quantity_remaining__gt=0, expiry_date__gte=today, expiry_date__lte=horizon
            ).values("product_id")
        )
    elif expiry == "expired":
        queryset = queryset.filter(
            pk__in=StockBatch.objects.filter(
                quantity_remaining__gt=0, expiry_date__lt=today
            ).values("product_id")
        )

    sort = request.GET.get("sort", "name")
    queryset = queryset.order_by(SORT_FIELDS.get(sort, "name"), "id")
    return queryset, term, sort


@login_required
def product_list(request):
    queryset, term, sort = _filtered_products(request)
    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    warning_days = request.shop.expiry_warning_days

    products = list(page_obj.object_list)
    _attach_expiry(products, warning_days)

    return render(
        request,
        "catalog/product_list.html",
        {
            "page_obj": page_obj,
            "page_numbers": page_range(page_obj),
            "products": products,
            "categories": Category.objects.active(),
            "term": term,
            "sort": sort,
            "item_label": "products",
            "total_count": paginator.count,
            "has_filters": any(
                request.GET.get(key) for key in ("q", "category", "stock", "expiry", "status")
            ),
        },
    )


def _attach_expiry(products, warning_days: int):
    """One query for every product's soonest live expiry, instead of N."""
    if not products:
        return
    rows = (
        StockBatch.objects.filter(
            product_id__in=[p.pk for p in products],
            quantity_remaining__gt=0,
            expiry_date__isnull=False,
        )
        .values("product_id")
        .annotate(soonest=Min("expiry_date"))
    )
    lookup = {row["product_id"]: row["soonest"] for row in rows}
    today = timezone.localdate()
    for product in products:
        expiry = lookup.get(product.pk)
        product.soonest_expiry = expiry
        if expiry is None:
            product.expiry_flag = None
        else:
            days = (expiry - today).days
            product.expiry_flag = (
                "expired" if days < 0 else ("expiring" if days <= warning_days else None)
            )


@login_required
def product_export(request):
    queryset, _term, _sort = _filtered_products(request)
    record(
        AuditAction.DATA_EXPORTED,
        request=request,
        summary=f"Exported {queryset.count()} products to CSV",
        details={"filters": dict(request.GET.items())},
    )

    def rows():
        for product in queryset.iterator(chunk_size=200):
            yield [
                product.sku,
                product.name,
                product.category.name,
                product.get_unit_display(),
                f"{product.cost_price:.2f}",
                f"{product.selling_price:.2f}",
                f"{product.stock_quantity:f}".rstrip("0").rstrip("."),
                f"{product.minimum_stock:f}".rstrip("0").rstrip("."),
                product.stock_status_label,
                f"{product.stock_value:.2f}",
                product.barcode,
                "Yes" if product.is_active else "No",
            ]

    return csv_response(
        "products",
        [
            "SKU",
            "Product",
            "Category",
            "Unit",
            "Cost price",
            "Selling price",
            "Stock on hand",
            "Low-stock level",
            "Stock status",
            "Stock value (cost)",
            "Barcode",
            "Active",
        ],
        rows(),
    )


@login_required
def product_detail(request, pk: int):
    product = get_object_or_404(
        Product.objects.select_related("category").with_stock_value(), pk=pk
    )
    warning_days = request.shop.expiry_warning_days

    batches = list(
        product.batches.select_related("supplier").filter(quantity_remaining__gt=0).fefo()
    )
    movements = product.movements.select_related("user", "sale", "batch").order_by(
        "-created_at", "-id"
    )[:10]
    recent_sales = (
        product.sale_items.select_related("sale", "sale__user")
        .filter(sale__status="completed")
        .order_by("-sale__completed_at")[:5]
    )
    sold_totals = product.sale_items.filter(sale__status="completed").aggregate(
        units=Coalesce(Sum("quantity"), Decimal("0")),
        revenue=Coalesce(Sum("line_total"), Decimal("0")),
        profit=Coalesce(Sum("gross_profit"), Decimal("0")),
    )

    return render(
        request,
        "catalog/product_detail.html",
        {
            "product": product,
            "batches": batches,
            "movements": movements,
            "recent_sales": recent_sales,
            "sold_totals": sold_totals,
            "expiry_state": product.expiry_state(warning_days),
            "soonest_expiry": product.earliest_expiry(),
            "warning_days": warning_days,
        },
    )


@login_required
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            product = form.save()
            record(
                AuditAction.PRODUCT_CREATED,
                request=request,
                obj=product,
                summary=f"Created product {product.name} ({product.sku})",
                details={
                    "sku": product.sku,
                    "category": product.category.name,
                    "selling_price": str(product.selling_price),
                    "cost_price": str(product.cost_price),
                },
            )
            opening = form.cleaned_data.get("opening_quantity")
            if opening:
                receive_stock(
                    product=product,
                    quantity=opening,
                    unit_cost=product.cost_price,
                    user=request.user,
                    expiry_date=form.cleaned_data.get("opening_expiry"),
                    notes="Opening stock recorded when the product was created.",
                    update_cost_price=False,
                    opening=True,
                )

        if getattr(form, "selling_below_cost", False):
            messages.warning(
                request,
                f"Heads up: the selling price of {product.name} is below its cost price.",
            )
        messages.success(request, f"{product.name} has been added.")
        if "save_and_add" in request.POST:
            return redirect("catalog:product_create")
        return redirect(product.get_absolute_url())

    return render(
        request,
        "catalog/product_form.html",
        {"form": form, "is_create": True, "heading": "Add a product"},
    )


@login_required
def product_edit(request, pk: int):
    product = get_object_or_404(Product, pk=pk)
    tracked = [
        "name",
        "sku",
        "category",
        "unit",
        "cost_price",
        "selling_price",
        "minimum_stock",
        "barcode",
        "is_active",
    ]
    # Snapshot first: validating the form writes the new values onto `product`.
    before = snapshot(product, tracked)
    form = ProductForm(request.POST or None, instance=product)

    if request.method == "POST" and form.is_valid():
        saved = form.save()
        diff = changed_fields(before, snapshot(saved, tracked))
        if diff:
            record(
                AuditAction.PRODUCT_UPDATED,
                request=request,
                obj=saved,
                summary=f"Updated product {saved.name} ({saved.sku})",
                details={"changes": diff},
            )
        if "is_active" in diff:
            record(
                AuditAction.PRODUCT_STATUS_CHANGED,
                request=request,
                obj=saved,
                summary=f"{saved.name} was marked {'available' if saved.is_active else 'not for sale'}",
            )
        messages.success(request, f"{saved.name} has been updated.")
        return redirect(saved.get_absolute_url())

    return render(
        request,
        "catalog/product_form.html",
        {"form": form, "object": product, "is_create": False, "heading": f"Edit {product.name}"},
    )


# --------------------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------------------
@login_required
def category_list(request):
    categories = Category.objects.annotate(
        product_count=Count("products", filter=Q(products__is_active=True))
    ).order_by("-is_active", "name")
    return render(request, "catalog/category_list.html", {"categories": categories})


@login_required
def category_create(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        category = form.save()
        record(
            AuditAction.CATEGORY_CREATED,
            request=request,
            obj=category,
            summary=f"Created category {category.name}",
        )
        messages.success(request, f"Category “{category.name}” has been added.")
        return redirect("catalog:category_list")
    return render(
        request, "catalog/category_form.html", {"form": form, "heading": "Add a category"}
    )


@login_required
def category_edit(request, pk: int):
    category = get_object_or_404(Category, pk=pk)
    tracked = ["name", "description", "is_active"]
    before = snapshot(category, tracked)
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        diff = changed_fields(before, snapshot(saved, tracked))
        if diff:
            record(
                AuditAction.CATEGORY_UPDATED,
                request=request,
                obj=saved,
                summary=f"Updated category {saved.name}",
                details={"changes": diff},
            )
        messages.success(request, f"Category “{saved.name}” has been updated.")
        return redirect("catalog:category_list")
    return render(
        request,
        "catalog/category_form.html",
        {"form": form, "object": category, "heading": f"Edit {category.name}"},
    )


# --------------------------------------------------------------------------------------
# Suppliers
# --------------------------------------------------------------------------------------
@login_required
def supplier_list(request):
    term = (request.GET.get("q") or "").strip()
    suppliers = Supplier.objects.annotate(delivery_count=Count("batches", distinct=True)).order_by(
        "-is_active", "name"
    )
    if term:
        suppliers = suppliers.filter(
            Q(name__icontains=term) | Q(location__icontains=term) | Q(phone__icontains=term)
        )
    return render(request, "catalog/supplier_list.html", {"suppliers": suppliers, "term": term})


@login_required
def supplier_detail(request, pk: int):
    supplier = get_object_or_404(Supplier, pk=pk)
    batches = supplier.batches.select_related("product", "received_by").order_by("-received_at")[
        :15
    ]
    totals = supplier.batches.aggregate(
        deliveries=Count("id"),
        value=Coalesce(
            Sum(F("quantity_received") * F("unit_cost")),
            Decimal("0"),
            output_field=Product._meta.get_field("cost_price"),
        ),
    )
    return render(
        request,
        "catalog/supplier_detail.html",
        {"supplier": supplier, "batches": batches, "totals": totals},
    )


@login_required
def supplier_create(request):
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        supplier = form.save()
        record(
            AuditAction.SUPPLIER_CREATED,
            request=request,
            obj=supplier,
            summary=f"Added supplier {supplier.name}",
        )
        messages.success(request, f"{supplier.name} has been added.")
        next_url = request.GET.get("next")
        if next_url == "receive":
            return redirect(f"{reverse('inventory:receive')}?supplier={supplier.pk}")
        return redirect(supplier.get_absolute_url())
    return render(
        request, "catalog/supplier_form.html", {"form": form, "heading": "Add a supplier"}
    )


@login_required
def supplier_edit(request, pk: int):
    supplier = get_object_or_404(Supplier, pk=pk)
    tracked = ["name", "phone", "email", "location", "notes", "is_active"]
    before = snapshot(supplier, tracked)
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        diff = changed_fields(before, snapshot(saved, tracked))
        if diff:
            record(
                AuditAction.SUPPLIER_UPDATED,
                request=request,
                obj=saved,
                summary=f"Updated supplier {saved.name}",
                details={"changes": diff},
            )
        messages.success(request, f"{saved.name} has been updated.")
        return redirect(saved.get_absolute_url())
    return render(
        request,
        "catalog/supplier_form.html",
        {"form": form, "object": supplier, "heading": f"Edit {supplier.name}"},
    )
