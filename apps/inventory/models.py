from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class BatchSource(models.TextChoices):
    OPENING = "opening", _("Opening stock")
    RECEIVED = "received", _("Stock received")
    RETURN = "return", _("Customer return")
    CORRECTION = "correction", _("Stock correction")


class StockBatchQuerySet(models.QuerySet):
    def live(self):
        return self.filter(quantity_remaining__gt=0)

    def expiring_before(self, day):
        return self.live().filter(expiry_date__isnull=False, expiry_date__lte=day)

    def expired(self, as_of=None):
        as_of = as_of or timezone.localdate()
        return self.live().filter(expiry_date__isnull=False, expiry_date__lt=as_of)

    def fefo(self):
        """First-expiry-first-out: dated batches first (soonest first), then oldest."""
        return self.order_by(F("expiry_date").asc(nulls_last=True), "received_at", "id")


class StockBatch(models.Model):
    """One delivery, opening count, return or upward correction of a product.

    A batch is where stock physically lives. ``quantity_remaining`` is decremented
    as the batch is consumed, which is what makes expiry tracking and cost
    snapshots possible.
    """

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="batches")
    supplier = models.ForeignKey(
        "catalog.Supplier",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="batches",
        verbose_name=_("supplier"),
    )
    source = models.CharField(
        max_length=16, choices=BatchSource.choices, default=BatchSource.RECEIVED
    )
    batch_number = models.CharField(
        _("batch number"),
        max_length=60,
        blank=True,
        help_text=_("Optional. The batch or lot code printed on the packaging."),
    )
    quantity_received = models.DecimalField(
        _("quantity"),
        max_digits=14,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    quantity_remaining = models.DecimalField(
        _("quantity remaining"), max_digits=14, decimal_places=3, editable=False
    )
    unit_cost = models.DecimalField(
        _("unit cost"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text=_("What you paid for one unit in this delivery."),
    )
    expiry_date = models.DateField(
        _("expiry date"),
        null=True,
        blank=True,
        help_text=_("Leave empty for products that do not expire."),
    )
    received_at = models.DateTimeField(_("date received"), default=timezone.now, db_index=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="batches_received",
    )
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StockBatchQuerySet.as_manager()

    class Meta:
        ordering = ["-received_at", "-id"]
        verbose_name = _("stock batch")
        verbose_name_plural = _("stock batches")
        indexes = [
            models.Index(fields=["product", "expiry_date"], name="batch_prod_expiry_idx"),
            models.Index(fields=["expiry_date"], name="batch_expiry_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_remaining__gte=Decimal("0")),
                name="batch_remaining_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(quantity_remaining__lte=F("quantity_received")),
                name="batch_remaining_within_received",
            ),
        ]

    def __str__(self) -> str:
        label = self.batch_number or f"#{self.pk}"
        return f"{self.product.name} · {label}"

    def save(self, *args, **kwargs):
        if self.pk is None and self.quantity_remaining is None:
            self.quantity_remaining = self.quantity_received
        return super().save(*args, **kwargs)

    @property
    def quantity_used(self) -> Decimal:
        return self.quantity_received - self.quantity_remaining

    @property
    def is_depleted(self) -> bool:
        return self.quantity_remaining <= 0

    @property
    def days_to_expiry(self) -> int | None:
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expired(self) -> bool:
        days = self.days_to_expiry
        return days is not None and days < 0

    def expiry_state(self, warning_days: int = 30) -> str | None:
        days = self.days_to_expiry
        if days is None:
            return None
        if days < 0:
            return "expired"
        if days <= warning_days:
            return "expiring"
        return None

    @property
    def remaining_value(self) -> Decimal:
        return self.quantity_remaining * self.unit_cost

    @property
    def display_label(self) -> str:
        parts = [self.batch_number or f"Batch {self.pk}"]
        if self.expiry_date:
            parts.append(f"exp {self.expiry_date:%d/%m/%Y}")
        return " · ".join(parts)


class MovementType(models.TextChoices):
    OPENING = "opening", _("Opening stock")
    RECEIVED = "received", _("Stock received")
    SALE = "sale", _("Sale")
    SALE_REVERSAL = "sale_reversal", _("Sale reversed")
    RETURN = "return", _("Customer return")
    DAMAGED = "damaged", _("Damaged stock")
    EXPIRED = "expired", _("Expired stock")
    MISSING = "missing", _("Missing stock")
    CORRECTION_UP = "correction_up", _("Positive correction")
    CORRECTION_DOWN = "correction_down", _("Negative correction")


#: Movement types that add stock. Everything else removes it.
INCREASE_TYPES = {
    MovementType.OPENING,
    MovementType.RECEIVED,
    MovementType.SALE_REVERSAL,
    MovementType.RETURN,
    MovementType.CORRECTION_UP,
}
DECREASE_TYPES = {
    MovementType.SALE,
    MovementType.DAMAGED,
    MovementType.EXPIRED,
    MovementType.MISSING,
    MovementType.CORRECTION_DOWN,
}

#: The subset a user can pick on the Stock adjustment screen.
ADJUSTMENT_TYPES = [
    MovementType.DAMAGED,
    MovementType.EXPIRED,
    MovementType.MISSING,
    MovementType.RETURN,
    MovementType.CORRECTION_UP,
    MovementType.CORRECTION_DOWN,
]

#: Plain-language help shown beside each adjustment choice.
ADJUSTMENT_HELP = {
    MovementType.DAMAGED: _("Broken, spoiled or unsellable items."),
    MovementType.EXPIRED: _("Items past their expiry date, removed from the shelf."),
    MovementType.MISSING: _("Stock that cannot be found during a count."),
    MovementType.RETURN: _("A customer brought an item back and it can be resold."),
    MovementType.CORRECTION_UP: _("A count found more stock than the system expected."),
    MovementType.CORRECTION_DOWN: _("A count found less stock than the system expected."),
}


class StockMovementQuerySet(models.QuerySet):
    def increases(self):
        return self.filter(quantity__gt=0)

    def decreases(self):
        return self.filter(quantity__lt=0)

    def with_related(self):
        return self.select_related("product", "product__category", "batch", "user", "sale")


class StockMovement(models.Model):
    """Immutable ledger entry. Every single change in stock has one.

    ``quantity`` is signed. ``quantity_before``/``quantity_after`` are the
    product's total on-hand quantity either side of this movement, captured
    inside the same locked transaction, so the ledger always reads as a
    continuous story.
    """

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="movements"
    )
    batch = models.ForeignKey(
        StockBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="movements"
    )
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_before = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_after = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Cost per unit at the moment of the movement."),
    )
    reason = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    sale = models.ForeignKey(
        "sales.Sale", null=True, blank=True, on_delete=models.PROTECT, related_name="movements"
    )
    sale_item = models.ForeignKey(
        "sales.SaleItem", null=True, blank=True, on_delete=models.PROTECT, related_name="movements"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = StockMovementQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("stock movement")
        indexes = [
            models.Index(fields=["product", "-created_at"], name="movement_product_idx"),
            models.Index(fields=["-created_at", "movement_type"], name="movement_recent_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(quantity=Decimal("0")), name="movement_quantity_not_zero"
            ),
            models.CheckConstraint(
                condition=Q(quantity_after__gte=Decimal("0")), name="movement_after_not_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_movement_type_display()} {self.signed_quantity} × {self.product.name}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("Stock movements are immutable; record a new movement instead.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Stock movements cannot be deleted.")

    # -- presentation ------------------------------------------------------------------
    @property
    def is_increase(self) -> bool:
        return self.quantity > 0

    @property
    def direction_label(self) -> str:
        """Never rely on colour alone — this word carries the meaning."""
        return "Added" if self.is_increase else "Removed"

    @property
    def signed_quantity(self) -> str:
        value = abs(self.quantity)
        text = self.product.format_quantity(value)
        return f"{'+' if self.is_increase else '−'}{text}"

    @property
    def value_effect(self) -> Decimal | None:
        if self.unit_cost is None:
            return None
        return self.quantity * self.unit_cost

    @property
    def related_label(self) -> str:
        if self.sale_id:
            return f"Sale {self.sale.sale_number}"
        if self.batch_id and self.movement_type in {MovementType.RECEIVED, MovementType.OPENING}:
            return self.batch.display_label
        return ""
