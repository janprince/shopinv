from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PaymentMethod(models.TextChoices):
    CASH = "cash", _("Cash")
    MOBILE_MONEY = "momo", _("Mobile Money")
    BANK_TRANSFER = "bank", _("Bank Transfer")


class SaleStatus(models.TextChoices):
    COMPLETED = "completed", _("Completed")
    REVERSED = "reversed", _("Reversed")


class SaleNumberCounter(models.Model):
    """One row per day, locked while a sale number is issued.

    Gives the shop sequential, human-readable numbers (S260822-0004) instead of
    database ids. A single till means there is effectively no contention here.
    """

    day = models.DateField(primary_key=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("sale number counter")

    def __str__(self) -> str:
        return f"{self.day}: {self.last_number}"


class SaleQuerySet(models.QuerySet):
    def completed(self):
        return self.filter(status=SaleStatus.COMPLETED)

    def counted(self):
        """Sales that count towards revenue — reversed sales never do."""
        return self.filter(status=SaleStatus.COMPLETED)

    def in_period(self, start, end):
        return self.filter(completed_at__gte=start, completed_at__lt=end)

    def with_related(self):
        return self.select_related("user", "reversed_by").prefetch_related("items__product")


class Sale(models.Model):
    """A completed walk-in transaction.

    Completed sales are immutable: money and stock have already moved. A mistake
    is corrected by reversing the sale, which writes new movements rather than
    rewriting the old ones.
    """

    sale_number = models.CharField(max_length=20, unique=True, editable=False)
    status = models.CharField(
        max_length=12, choices=SaleStatus.choices, default=SaleStatus.COMPLETED, db_index=True
    )

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    discount = models.DecimalField(
        _("discount"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    #: Snapshot of what the goods cost us, from the batches actually consumed.
    cost_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    gross_profit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    payment_method = models.CharField(
        _("payment method"),
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    amount_received = models.DecimalField(
        _("amount received"), max_digits=12, decimal_places=2, null=True, blank=True
    )
    change_due = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payment_reference = models.CharField(
        _("payment reference"),
        max_length=60,
        blank=True,
        help_text=_("Optional. Mobile Money or bank transaction reference."),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="sales"
    )
    completed_at = models.DateTimeField(default=timezone.now, db_index=True)
    notes = models.CharField(max_length=200, blank=True)

    #: Sent by the till with each submission. A retry after a dropped connection
    #: reuses the key, so the sale can never be recorded twice.
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    reversal_reason = models.CharField(max_length=300, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_reversed",
    )

    objects = SaleQuerySet.as_manager()

    class Meta:
        ordering = ["-completed_at", "-id"]
        indexes = [
            models.Index(fields=["-completed_at", "status"], name="sale_recent_idx"),
            models.Index(fields=["payment_method"], name="sale_payment_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total__gte=Decimal("0")) & Q(discount__gte=Decimal("0")),
                name="sale_amounts_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(discount__lte=models.F("subtotal")),
                name="sale_discount_within_subtotal",
            ),
        ]

    def __str__(self) -> str:
        return self.sale_number

    def get_absolute_url(self):
        return reverse("sales:detail", args=[self.pk])

    def delete(self, *args, **kwargs):
        raise PermissionDenied(
            "Completed sales are never deleted. Reverse the sale instead so the "
            "reason stays on the record."
        )

    @property
    def is_reversed(self) -> bool:
        return self.status == SaleStatus.REVERSED

    @property
    def item_count(self) -> int:
        return self.items.count()

    @property
    def total_units(self) -> Decimal:
        return sum((item.quantity for item in self.items.all()), Decimal("0"))

    @property
    def margin_percent(self) -> Decimal | None:
        if not self.total:
            return None
        return (self.gross_profit / self.total) * 100

    @property
    def requires_cash_fields(self) -> bool:
        return self.payment_method == PaymentMethod.CASH

    @staticmethod
    def new_idempotency_key() -> str:
        return str(uuid.uuid4())


class SaleItem(models.Model):
    """One line of a sale, with price and cost frozen at the moment of sale.

    Editing a product's price tomorrow must not change what last week's reports say.
    """

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="items")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="sale_items"
    )

    # Snapshots — these keep receipts and reports readable even if the product changes.
    product_name = models.CharField(max_length=140)
    sku = models.CharField(max_length=32)
    unit = models.CharField(max_length=10)

    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    line_cost = models.DecimalField(max_digits=12, decimal_places=2)
    gross_profit = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=Decimal("0")), name="saleitem_qty_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.product_name}"

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Sale lines cannot be deleted. Reverse the sale instead.")

    @property
    def display_quantity(self) -> str:
        from apps.catalog.models import UNIT_ABBREVIATIONS

        text = f"{self.quantity.normalize():f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return f"{text} {UNIT_ABBREVIATIONS.get(self.unit, self.unit)}"
