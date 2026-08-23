"""Every change to stock goes through this module.

Rules enforced here, not in views or forms:

* Stock is only ever changed by creating a :class:`StockMovement`.
* Stock can never go negative — the attempt raises before anything is written.
* The product row is locked first, so simultaneous tills queue instead of racing.
* ``Product.stock_quantity`` is a cache of the batch totals, updated in the same
  transaction as the movement that changed it.
* Products with expiry dates are consumed first-expiry-first-out.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.catalog.models import WHOLE_UNITS, Product
from apps.core.utils import money
from apps.core.utils import quantity as quantise

from .models import (
    ADJUSTMENT_TYPES,
    DECREASE_TYPES,
    INCREASE_TYPES,
    BatchSource,
    MovementType,
    StockBatch,
    StockMovement,
)

ZERO = Decimal("0")


class StockError(Exception):
    """Raised for anything the user needs to read and act on."""


class InsufficientStock(StockError):
    def __init__(self, product, requested: Decimal, available: Decimal):
        self.product = product
        self.requested = requested
        self.available = available
        super().__init__(
            f"Not enough {product.name} in stock. "
            f"You asked for {product.format_quantity(requested)} but only "
            f"{product.format_quantity(available)} is available."
        )


@dataclass(frozen=True)
class Consumption:
    """One batch's contribution to a stock reduction."""

    batch: StockBatch
    quantity: Decimal
    unit_cost: Decimal

    @property
    def cost(self) -> Decimal:
        return self.quantity * self.unit_cost


# --------------------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------------------
def validate_quantity(product: Product, value) -> Decimal:
    """Normalise a user-supplied quantity and reject nonsense early."""
    try:
        qty = quantise(Decimal(str(value)))
    except Exception as exc:
        raise StockError("Enter a valid quantity.") from exc
    if qty <= ZERO:
        raise StockError("Quantity must be greater than zero.")
    if product.unit in WHOLE_UNITS and qty != qty.to_integral_value():
        raise StockError(
            f"{product.name} is counted in whole {product.get_unit_display().lower()}s. "
            "Enter a whole number."
        )
    return qty


def lock_product(product_id: int) -> Product:
    """Take the row lock that serialises all stock changes for this product."""
    return Product.objects.select_for_update().get(pk=product_id)


def available_quantity(product_id: int) -> Decimal:
    """Authoritative on-hand total, summed from live batches."""
    total = StockBatch.objects.filter(product_id=product_id, quantity_remaining__gt=0).aggregate(
        total=Sum("quantity_remaining")
    )["total"]
    return total or ZERO


# --------------------------------------------------------------------------------------
# Primitives — always called inside an open transaction with the product locked
# --------------------------------------------------------------------------------------
def _write_movement(
    *,
    product: Product,
    movement_type: str,
    signed_quantity: Decimal,
    batch: StockBatch | None,
    unit_cost: Decimal | None,
    user,
    reason: str = "",
    notes: str = "",
    sale=None,
    sale_item=None,
) -> StockMovement:
    before = product.stock_quantity
    after = before + signed_quantity
    if after < ZERO:
        raise InsufficientStock(product, abs(signed_quantity), before)

    movement = StockMovement.objects.create(
        product=product,
        batch=batch,
        movement_type=movement_type,
        quantity=signed_quantity,
        quantity_before=before,
        quantity_after=after,
        unit_cost=money(unit_cost) if unit_cost is not None else None,
        reason=reason[:200],
        notes=notes,
        sale=sale,
        sale_item=sale_item,
        user=user,
    )
    Product.objects.filter(pk=product.pk).update(
        stock_quantity=F("stock_quantity") + signed_quantity, updated_at=timezone.now()
    )
    product.stock_quantity = after
    return movement


def add_stock(
    *,
    product: Product,
    quantity: Decimal,
    movement_type: str,
    user,
    unit_cost: Decimal,
    supplier=None,
    batch: StockBatch | None = None,
    batch_number: str = "",
    expiry_date=None,
    source: str = BatchSource.RECEIVED,
    received_at=None,
    reason: str = "",
    notes: str = "",
    sale=None,
    sale_item=None,
) -> tuple[StockBatch, StockMovement]:
    """Add stock, either into an existing batch or into a new one.

    Restoring into an existing batch is how a sale reversal puts goods back where
    they came from, keeping expiry dates and costs intact.
    """
    if movement_type not in INCREASE_TYPES:
        raise StockError("That movement type does not add stock.")

    if batch is not None:
        StockBatch.objects.filter(pk=batch.pk).update(
            quantity_remaining=F("quantity_remaining") + quantity
        )
        batch.refresh_from_db(fields=["quantity_remaining"])
        unit_cost = batch.unit_cost
    else:
        batch = StockBatch.objects.create(
            product=product,
            supplier=supplier,
            source=source,
            batch_number=batch_number.strip(),
            quantity_received=quantity,
            quantity_remaining=quantity,
            unit_cost=money(unit_cost),
            expiry_date=expiry_date,
            received_at=received_at or timezone.now(),
            received_by=user,
            notes=notes,
        )

    movement = _write_movement(
        product=product,
        movement_type=movement_type,
        signed_quantity=quantity,
        batch=batch,
        unit_cost=batch.unit_cost,
        user=user,
        reason=reason,
        notes=notes,
        sale=sale,
        sale_item=sale_item,
    )
    return batch, movement


def remove_stock(
    *,
    product: Product,
    quantity: Decimal,
    movement_type: str,
    user,
    batch: StockBatch | None = None,
    reason: str = "",
    notes: str = "",
    sale=None,
    sale_item=None,
) -> list[Consumption]:
    """Take stock out, first-expiry-first-out unless a specific batch is named.

    Writes one movement per batch touched so the ledger shows exactly which
    goods left the shelf.
    """
    if movement_type not in DECREASE_TYPES:
        raise StockError("That movement type does not remove stock.")

    batches = StockBatch.objects.select_for_update().filter(
        product=product, quantity_remaining__gt=0
    )
    if batch is not None:
        batches = batches.filter(pk=batch.pk)
    candidates = list(batches.fefo())

    obtainable = sum((b.quantity_remaining for b in candidates), ZERO)
    if obtainable < quantity:
        raise InsufficientStock(product, quantity, obtainable)

    consumptions: list[Consumption] = []
    outstanding = quantity
    for candidate in candidates:
        if outstanding <= ZERO:
            break
        take = min(candidate.quantity_remaining, outstanding)
        StockBatch.objects.filter(pk=candidate.pk).update(
            quantity_remaining=F("quantity_remaining") - take
        )
        candidate.quantity_remaining -= take
        outstanding -= take

        _write_movement(
            product=product,
            movement_type=movement_type,
            signed_quantity=-take,
            batch=candidate,
            unit_cost=candidate.unit_cost,
            user=user,
            reason=reason,
            notes=notes,
            sale=sale,
            sale_item=sale_item,
        )
        consumptions.append(Consumption(candidate, take, candidate.unit_cost))

    return consumptions


# --------------------------------------------------------------------------------------
# Public operations
# --------------------------------------------------------------------------------------
@transaction.atomic
def receive_stock(
    *,
    product: Product,
    quantity,
    unit_cost,
    user,
    supplier=None,
    batch_number: str = "",
    expiry_date=None,
    notes: str = "",
    received_at=None,
    update_cost_price: bool = True,
    opening: bool = False,
) -> StockBatch:
    """Record a delivery (or an opening count) and put it on the shelf."""
    from apps.core.audit import AuditAction, record

    product = lock_product(product.pk)
    qty = validate_quantity(product, quantity)
    cost = money(unit_cost)
    if cost < ZERO:
        raise StockError("Unit cost cannot be negative.")

    movement_type = MovementType.OPENING if opening else MovementType.RECEIVED
    source = BatchSource.OPENING if opening else BatchSource.RECEIVED

    batch, _movement = add_stock(
        product=product,
        quantity=qty,
        movement_type=movement_type,
        user=user,
        unit_cost=cost,
        supplier=supplier,
        batch_number=batch_number,
        expiry_date=expiry_date,
        source=source,
        received_at=received_at,
        reason="Opening stock count" if opening else "Stock received",
        notes=notes,
    )

    # Keep the product's default cost current so the next sale's profit estimate
    # and the receiving form both start from a realistic number.
    if update_cost_price and cost > ZERO and cost != product.cost_price:
        Product.objects.filter(pk=product.pk).update(cost_price=cost)
        product.cost_price = cost

    record(
        AuditAction.OPENING_STOCK if opening else AuditAction.STOCK_RECEIVED,
        actor=user,
        obj=product,
        summary=(
            f"{'Opening stock' if opening else 'Received'} "
            f"{product.format_quantity(qty)} of {product.name}"
        ),
        details={
            "quantity": str(qty),
            "unit_cost": str(cost),
            "supplier": supplier.name if supplier else None,
            "batch_number": batch.batch_number or None,
            "expiry_date": str(expiry_date) if expiry_date else None,
            "batch_id": batch.pk,
        },
    )
    return batch


@transaction.atomic
def adjust_stock(
    *,
    product: Product,
    movement_type: str,
    quantity,
    reason: str,
    user,
    batch: StockBatch | None = None,
    notes: str = "",
) -> list[StockMovement]:
    """Record damage, expiry, loss, a customer return or a counting correction."""
    from apps.core.audit import AuditAction, record

    if movement_type not in {t.value for t in ADJUSTMENT_TYPES}:
        raise StockError("Choose a valid adjustment type.")
    reason = (reason or "").strip()
    if not reason:
        raise StockError("A reason is required for every stock adjustment.")

    product = lock_product(product.pk)
    qty = validate_quantity(product, quantity)
    before = product.stock_quantity

    if movement_type in INCREASE_TYPES:
        source = (
            BatchSource.RETURN if movement_type == MovementType.RETURN else BatchSource.CORRECTION
        )
        unit_cost = batch.unit_cost if batch is not None else product.cost_price
        _batch, movement = add_stock(
            product=product,
            quantity=qty,
            movement_type=movement_type,
            user=user,
            unit_cost=unit_cost,
            batch=batch,
            source=source,
            batch_number=batch.batch_number if batch else "",
            expiry_date=batch.expiry_date if batch else None,
            reason=reason,
            notes=notes,
        )
        movements = [movement]
    else:
        consumptions = remove_stock(
            product=product,
            quantity=qty,
            movement_type=movement_type,
            user=user,
            batch=batch,
            reason=reason,
            notes=notes,
        )
        movements = [c.batch.movements.order_by("-id").first() for c in consumptions]

    label = MovementType(movement_type).label
    record(
        AuditAction.STOCK_ADJUSTED,
        actor=user,
        obj=product,
        summary=f"{label}: {product.format_quantity(qty)} of {product.name}",
        details={
            "movement_type": movement_type,
            "quantity": str(qty),
            "reason": reason,
            "notes": notes or None,
            "batch_id": batch.pk if batch else None,
            "stock_before": str(before),
            "stock_after": str(product.stock_quantity),
        },
    )
    return movements


def recalculate_product_stock(product_id: int) -> Decimal:
    """Repair helper: rebuild the cached total from the batches themselves."""
    total = available_quantity(product_id)
    Product.objects.filter(pk=product_id).update(stock_quantity=total)
    return total
