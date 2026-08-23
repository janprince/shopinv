"""Sale completion and reversal.

A sale is the one place where money and stock move together, so the whole
operation is a single database transaction. If any line fails — a product went
out of stock two seconds ago — nothing at all is written and the till shows why.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.audit import AuditAction, record
from apps.core.utils import money
from apps.inventory.models import MovementType, StockMovement
from apps.inventory.services import (
    InsufficientStock,
    StockError,
    add_stock,
    lock_product,
    remove_stock,
    validate_quantity,
)

from .models import PaymentMethod, Sale, SaleItem, SaleNumberCounter, SaleStatus

logger = logging.getLogger("jcf.sales")
ZERO = Decimal("0")


class SaleError(StockError):
    """Anything that stops a sale, phrased for the person at the till."""


@dataclass
class CartLine:
    product_id: int
    quantity: Decimal


def next_sale_number(when=None) -> str:
    """Sequential per-day number, e.g. S260822-0004.

    The counter row is locked, so two tills can never be handed the same number.
    """
    day = (when or timezone.localtime()).date()
    counter, _created = SaleNumberCounter.objects.select_for_update().get_or_create(day=day)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return f"S{day:%y%m%d}-{counter.last_number:04d}"


def normalise_lines(raw_lines) -> list[CartLine]:
    """Merge repeats of the same product and drop empties."""
    merged: dict[int, Decimal] = {}
    order: list[int] = []
    for entry in raw_lines or []:
        try:
            product_id = int(entry["product_id"])
            qty = Decimal(str(entry["quantity"]))
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise SaleError("The sale contains an item that could not be read.") from exc
        if qty <= ZERO:
            continue
        if product_id not in merged:
            order.append(product_id)
            merged[product_id] = ZERO
        merged[product_id] += qty
    if not merged:
        raise SaleError("Add at least one product before completing the sale.")
    if len(merged) > 200:
        raise SaleError("A single sale cannot contain more than 200 different products.")
    return [CartLine(pid, merged[pid]) for pid in order]


def complete_sale(
    *,
    raw_lines,
    user,
    payment_method: str = PaymentMethod.CASH,
    amount_received=None,
    discount=ZERO,
    payment_reference: str = "",
    notes: str = "",
    idempotency_key: str | None = None,
) -> tuple[Sale, bool]:
    """Record a completed walk-in sale.

    Returns ``(sale, created)``. ``created`` is False when this exact submission
    was already recorded — that is how a retry after a lost connection resolves
    without charging the customer twice.
    """
    if idempotency_key:
        existing = Sale.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            logger.info("Duplicate submission for sale %s ignored", existing.sale_number)
            return existing, False

    lines = normalise_lines(raw_lines)

    if payment_method not in PaymentMethod.values:
        raise SaleError("Choose a valid payment method.")

    try:
        with transaction.atomic():
            sale = _write_sale(
                lines=lines,
                user=user,
                payment_method=payment_method,
                amount_received=amount_received,
                discount=discount,
                payment_reference=payment_reference,
                notes=notes,
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # Two identical submissions raced. The winner's sale is the real one.
        if idempotency_key:
            existing = Sale.objects.filter(idempotency_key=idempotency_key).first()
            if existing is not None:
                return existing, False
        raise

    record(
        AuditAction.SALE_COMPLETED,
        actor=user,
        obj=sale,
        summary=f"Sale {sale.sale_number} completed — {money(sale.total)} ({sale.get_payment_method_display()})",
        details={
            "total": str(sale.total),
            "discount": str(sale.discount),
            "cost_total": str(sale.cost_total),
            "gross_profit": str(sale.gross_profit),
            "payment_method": sale.payment_method,
            "lines": [
                {
                    "sku": item.sku,
                    "quantity": str(item.quantity),
                    "unit_price": str(item.unit_price),
                }
                for item in sale.items.all()
            ],
        },
    )
    return sale, True


def _write_sale(
    *,
    lines: list[CartLine],
    user,
    payment_method,
    amount_received,
    discount,
    payment_reference,
    notes,
    idempotency_key,
) -> Sale:
    # Deterministic lock order stops two simultaneous sales from deadlocking on
    # the same pair of products.
    ordered = sorted(lines, key=lambda line: line.product_id)
    locked: dict[int, Product] = {}
    for line in ordered:
        try:
            product = lock_product(line.product_id)
        except Product.DoesNotExist as exc:
            raise SaleError("One of the items is no longer available.") from exc
        if not product.is_active:
            raise SaleError(f"{product.name} is no longer on sale and was removed from the cart.")
        locked[line.product_id] = product

    subtotal = ZERO
    prepared = []
    for line in lines:
        product = locked[line.product_id]
        qty = validate_quantity(product, line.quantity)
        if product.stock_quantity < qty:
            raise InsufficientStock(product, qty, product.stock_quantity)
        unit_price = money(product.selling_price)
        line_total = money(unit_price * qty)
        subtotal += line_total
        prepared.append((product, qty, unit_price, line_total))

    subtotal = money(subtotal)
    discount = money(discount or ZERO)
    if discount < ZERO:
        raise SaleError("Discount cannot be negative.")
    if discount > subtotal:
        raise SaleError("Discount cannot be more than the sale total.")
    total = money(subtotal - discount)

    change_due = None
    received = None
    if payment_method == PaymentMethod.CASH and amount_received not in (None, ""):
        received = money(amount_received)
        if received < total:
            raise SaleError(f"Cash received ({money(received)}) is less than the total ({total}).")
        change_due = money(received - total)

    sale = Sale.objects.create(
        sale_number=next_sale_number(),
        status=SaleStatus.COMPLETED,
        subtotal=subtotal,
        discount=discount,
        total=total,
        payment_method=payment_method,
        amount_received=received,
        change_due=change_due,
        payment_reference=(payment_reference or "").strip()[:60],
        notes=(notes or "").strip()[:200],
        user=user,
        completed_at=timezone.now(),
        idempotency_key=idempotency_key or None,
    )

    cost_total = ZERO
    for product, qty, unit_price, line_total in prepared:
        item = SaleItem.objects.create(
            sale=sale,
            product=product,
            product_name=product.name,
            sku=product.sku,
            unit=product.unit,
            quantity=qty,
            unit_price=unit_price,
            unit_cost=ZERO,
            line_total=line_total,
            line_cost=ZERO,
            gross_profit=ZERO,
        )
        consumptions = remove_stock(
            product=product,
            quantity=qty,
            movement_type=MovementType.SALE,
            user=user,
            reason=f"Sale {sale.sale_number}",
            sale=sale,
            sale_item=item,
        )
        # Cost comes from the batches actually sold, not from today's price list.
        line_cost = money(sum((c.cost for c in consumptions), ZERO))
        item.line_cost = line_cost
        item.unit_cost = money(line_cost / qty) if qty else ZERO
        item.gross_profit = money(line_total - line_cost)
        item.save(update_fields=["line_cost", "unit_cost", "gross_profit"])
        cost_total += line_cost

    sale.cost_total = money(cost_total)
    # The discount is a real cost to the shop, so it comes off the profit estimate.
    sale.gross_profit = money(total - sale.cost_total)
    sale.save(update_fields=["cost_total", "gross_profit"])
    return sale


@transaction.atomic
def reverse_sale(*, sale: Sale, user, reason: str) -> Sale:
    """Undo a completed sale by putting the goods back and writing new movements.

    The original sale and its movements are left exactly as they were; the
    reversal is additive, so an auditor can still see what happened first.
    """
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise SaleError("Give a short reason for the reversal (at least 5 characters).")

    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status == SaleStatus.REVERSED:
        raise SaleError(f"Sale {sale.sale_number} has already been reversed.")

    sale_movements = list(
        StockMovement.objects.select_related("batch", "product")
        .filter(sale=sale, movement_type=MovementType.SALE)
        .order_by("id")
    )
    if not sale_movements:
        raise SaleError("This sale has no stock movements to reverse.")

    for original in sale_movements:
        product = lock_product(original.product_id)
        add_stock(
            product=product,
            quantity=abs(original.quantity),
            movement_type=MovementType.SALE_REVERSAL,
            user=user,
            unit_cost=original.unit_cost or product.cost_price,
            batch=original.batch,
            reason=f"Reversal of sale {sale.sale_number}",
            notes=reason,
            sale=sale,
            sale_item=original.sale_item,
        )

    sale.status = SaleStatus.REVERSED
    sale.reversal_reason = reason[:300]
    sale.reversed_at = timezone.now()
    sale.reversed_by = user
    sale.save(update_fields=["status", "reversal_reason", "reversed_at", "reversed_by"])

    record(
        AuditAction.SALE_REVERSED,
        actor=user,
        obj=sale,
        summary=f"Sale {sale.sale_number} reversed — {money(sale.total)} returned to stock",
        details={"reason": reason, "total": str(sale.total), "items": sale.items.count()},
    )
    return sale
