from __future__ import annotations

from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce, Lower
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel

SKU_VALIDATOR = RegexValidator(
    r"^[A-Za-z0-9][A-Za-z0-9\-_/]{1,31}$",
    _("Use letters, numbers, dashes or slashes (2–32 characters)."),
)
PHONE_VALIDATOR = RegexValidator(
    r"^[0-9+\-\s()]{7,20}$",
    _("Enter a valid phone number, for example 024 123 4567 or +233 24 123 4567."),
)


class Unit(models.TextChoices):
    """Units of measurement. Whole-unit types are validated to whole numbers."""

    PIECE = "piece", _("Piece")
    BOTTLE = "bottle", _("Bottle")
    PACK = "pack", _("Pack")
    SACHET = "sachet", _("Sachet")
    BOX = "box", _("Box")
    BAG = "bag", _("Bag")
    GRAM = "g", _("Gram (g)")
    KILOGRAM = "kg", _("Kilogram (kg)")
    MILLILITRE = "ml", _("Millilitre (ml)")
    LITRE = "l", _("Litre (L)")


#: Units that cannot be sold in fractions. Everything else allows 3 decimal places.
WHOLE_UNITS = {
    Unit.PIECE,
    Unit.BOTTLE,
    Unit.PACK,
    Unit.SACHET,
    Unit.BOX,
    Unit.BAG,
}

UNIT_ABBREVIATIONS = {
    Unit.PIECE: "pc",
    Unit.BOTTLE: "btl",
    Unit.PACK: "pack",
    Unit.SACHET: "sachet",
    Unit.BOX: "box",
    Unit.BAG: "bag",
    Unit.GRAM: "g",
    Unit.KILOGRAM: "kg",
    Unit.MILLILITRE: "ml",
    Unit.LITRE: "L",
}


class ActiveQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Category(TimeStampedModel):
    name = models.CharField(_("category name"), max_length=80)
    slug = models.SlugField(max_length=90, unique=True, blank=True)
    description = models.CharField(_("description"), max_length=200, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    objects = ActiveQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name_plural = _("categories")
        constraints = [
            models.UniqueConstraint(Lower("name"), name="category_name_unique_ci"),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        if not self.slug:
            base = slugify(self.name)[:80] or "category"
            slug, counter = base, 2
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        return super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"{reverse('catalog:product_list')}?category={self.pk}"


class Supplier(TimeStampedModel):
    name = models.CharField(_("supplier name"), max_length=120)
    phone = models.CharField(
        _("phone number"), max_length=20, blank=True, validators=[PHONE_VALIDATOR]
    )
    email = models.EmailField(_("email address"), blank=True)
    location = models.CharField(_("location or address"), max_length=200, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    objects = ActiveQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="supplier_name_unique_ci"),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.email = (self.email or "").strip().lower()
        return super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:supplier_detail", args=[self.pk])


class StockStatus(models.TextChoices):
    OUT = "out", _("Out of stock")
    LOW = "low", _("Low stock")
    IN = "in", _("In stock")


class ProductQuerySet(ActiveQuerySet):
    def with_stock_value(self):
        """Annotate the cost value of remaining stock, batch by batch."""
        from apps.inventory.models import StockBatch

        value = models.Subquery(
            StockBatch.objects.filter(product=models.OuterRef("pk"), quantity_remaining__gt=0)
            .values("product")
            .annotate(total=Sum(F("quantity_remaining") * F("unit_cost")))
            .values("total")[:1],
            output_field=models.DecimalField(max_digits=14, decimal_places=2),
        )
        return self.annotate(stock_cost_value=Coalesce(value, Decimal("0")))

    def low_stock(self):
        return self.filter(stock_quantity__lte=F("minimum_stock"), stock_quantity__gt=0)

    def out_of_stock(self):
        return self.filter(stock_quantity__lte=0)

    def needs_restock(self):
        return self.filter(stock_quantity__lte=F("minimum_stock"))

    def search(self, term: str):
        term = (term or "").strip()
        if not term:
            return self
        return self.filter(
            Q(name__icontains=term)
            | Q(sku__icontains=term)
            | Q(barcode__iexact=term)
            | Q(category__name__icontains=term)
        )


class Product(TimeStampedModel):
    name = models.CharField(_("product name"), max_length=140)
    sku = models.CharField(
        _("SKU / product code"),
        max_length=32,
        unique=True,
        validators=[SKU_VALIDATOR],
        help_text=_("A short unique code you use to identify this product, e.g. HON-500."),
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products", verbose_name=_("category")
    )
    description = models.TextField(_("description"), blank=True)
    unit = models.CharField(
        _("unit of measurement"), max_length=10, choices=Unit.choices, default=Unit.PIECE
    )
    cost_price = models.DecimalField(
        _("cost price"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text=_("What you normally pay your supplier for one unit."),
    )
    selling_price = models.DecimalField(
        _("selling price"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text=_("What the customer pays for one unit."),
    )
    minimum_stock = models.DecimalField(
        _("low-stock level"),
        max_digits=12,
        decimal_places=3,
        default=Decimal("5"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text=_("Warn me when stock falls to this level or below."),
    )
    barcode = models.CharField(
        _("barcode"),
        max_length=64,
        blank=True,
        help_text=_("Optional. Scan or type the barcode printed on the product."),
    )
    #: Denormalised on-hand total, kept in step with StockBatch rows inside the same
    #: transaction as every movement. Never edited by a form — see apps.inventory.services.
    stock_quantity = models.DecimalField(
        _("stock on hand"),
        max_digits=14,
        decimal_places=3,
        default=Decimal("0"),
        editable=False,
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Inactive products are hidden from the sales screen but keep their history."),
    )

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "name"], name="product_active_name_idx"),
            models.Index(fields=["stock_quantity"], name="product_stock_idx"),
            models.Index(fields=["barcode"], name="product_barcode_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(stock_quantity__gte=Decimal("0")),
                name="product_stock_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(selling_price__gte=Decimal("0")) & Q(cost_price__gte=Decimal("0")),
                name="product_prices_not_negative",
            ),
            models.UniqueConstraint(Lower("sku"), name="product_sku_unique_ci"),
            models.UniqueConstraint(
                Lower("barcode"), condition=~Q(barcode=""), name="product_barcode_unique_ci"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.sku = self.sku.strip().upper()
        self.barcode = (self.barcode or "").strip()
        return super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:product_detail", args=[self.pk])

    # -- presentation helpers ----------------------------------------------------------
    @property
    def unit_label(self) -> str:
        return UNIT_ABBREVIATIONS.get(self.unit, self.unit)

    @property
    def allows_fractions(self) -> bool:
        return self.unit not in WHOLE_UNITS

    @property
    def quantity_step(self) -> str:
        return "0.001" if self.allows_fractions else "1"

    def format_quantity(self, value=None) -> str:
        value = self.stock_quantity if value is None else value
        value = Decimal(value)
        if self.allows_fractions:
            text = f"{value.normalize():f}"
            if "." in text:
                text = text.rstrip("0").rstrip(".")
        else:
            text = f"{int(value)}"
        return f"{text} {self.unit_label}"

    @property
    def display_stock(self) -> str:
        return self.format_quantity()

    @property
    def stock_status(self) -> str:
        if self.stock_quantity <= 0:
            return StockStatus.OUT
        if self.stock_quantity <= self.minimum_stock:
            return StockStatus.LOW
        return StockStatus.IN

    @property
    def stock_status_label(self) -> str:
        return StockStatus(self.stock_status).label

    @property
    def unit_margin(self) -> Decimal:
        return self.selling_price - self.cost_price

    @property
    def margin_percent(self) -> Decimal | None:
        if not self.selling_price:
            return None
        return (self.unit_margin / self.selling_price) * 100

    @property
    def stock_value(self) -> Decimal:
        """Cost value of stock on hand, using each batch's own cost."""
        cached = getattr(self, "stock_cost_value", None)
        if cached is not None:
            return cached
        total = self.batches.filter(quantity_remaining__gt=0).aggregate(
            total=Coalesce(
                Sum(F("quantity_remaining") * F("unit_cost")),
                Decimal("0"),
                output_field=models.DecimalField(max_digits=14, decimal_places=2),
            )
        )["total"]
        return total

    @property
    def retail_stock_value(self) -> Decimal:
        return self.stock_quantity * self.selling_price

    def earliest_expiry(self):
        batch = (
            self.batches.filter(quantity_remaining__gt=0, expiry_date__isnull=False)
            .order_by("expiry_date")
            .first()
        )
        return batch.expiry_date if batch else None

    def expiry_state(self, warning_days: int = 30) -> str | None:
        """``expired`` / ``expiring`` / ``None`` for the soonest live batch."""
        expiry = self.earliest_expiry()
        if expiry is None:
            return None
        days = (expiry - timezone.localdate()).days
        if days < 0:
            return "expired"
        if days <= warning_days:
            return "expiring"
        return None
