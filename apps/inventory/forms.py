from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.models import WHOLE_UNITS, Category, Product, Supplier

from .models import ADJUSTMENT_HELP, ADJUSTMENT_TYPES, INCREASE_TYPES, MovementType, StockBatch

TEXT = {"class": "form-control"}
SELECT = {"class": "form-select"}


class HtmlDateInput(forms.DateInput):
    """A native date picker that actually shows the value it was given.

    ``<input type="date">`` only accepts ISO-8601. Django localises date input
    for the en-gb locale, so an initial value renders as 23/08/2026, the browser
    rejects it, and the field appears blank — including when a form is redisplayed
    after a validation error, which silently loses what the user typed.
    """

    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs={**TEXT, **(attrs or {}), "type": "date"}, format="%Y-%m-%d")


class ProductChoiceField(forms.ModelChoiceField):
    """Shows stock and unit in the option label so the picker is self-explanatory."""

    def label_from_instance(self, obj: Product) -> str:
        return f"{obj.name} · {obj.sku} · {obj.display_stock} in stock"


class ReceiveStockForm(forms.Form):
    product = ProductChoiceField(
        label="Product",
        queryset=Product.objects.none(),
        empty_label="Choose a product…",
        widget=forms.Select(attrs={**SELECT, "data-autofocus": "true"}),
    )
    quantity = forms.DecimalField(
        label="Quantity received",
        min_value=Decimal("0.001"),
        max_digits=14,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={**TEXT, "step": "0.001", "min": "0", "inputmode": "decimal", "placeholder": "0"}
        ),
        help_text="How much arrived in this delivery.",
    )
    unit_cost = forms.DecimalField(
        label="Cost per unit",
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={**TEXT, "step": "0.01", "min": "0", "inputmode": "decimal"}
        ),
        help_text="What you paid the supplier for one unit.",
    )
    supplier = forms.ModelChoiceField(
        label="Supplier",
        queryset=Supplier.objects.none(),
        required=False,
        empty_label="Not recorded",
        widget=forms.Select(attrs=SELECT),
    )
    batch_number = forms.CharField(
        label="Batch or lot number",
        required=False,
        max_length=60,
        widget=forms.TextInput(attrs={**TEXT, "placeholder": "e.g. LOT-2024-08"}),
        help_text="Copy it from the packaging if there is one.",
    )
    expiry_date = forms.DateField(
        label="Expiry date",
        required=False,
        widget=HtmlDateInput(),
        help_text="Leave empty for products that do not expire.",
    )
    received_on = forms.DateField(
        label="Date received",
        required=False,
        widget=HtmlDateInput(),
        help_text="Defaults to today.",
    )
    notes = forms.CharField(
        label="Notes",
        required=False,
        widget=forms.Textarea(
            attrs={
                **TEXT,
                "rows": 2,
                "placeholder": "Anything worth remembering about this delivery",
            }
        ),
    )
    update_cost_price = forms.BooleanField(
        label="Use this cost as the product's new default cost price",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Keeps profit estimates in line with what you actually pay.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = (
            Product.objects.active().select_related("category").order_by("category__name", "name")
        )
        self.fields["supplier"].queryset = Supplier.objects.active().order_by("name")

    def clean_expiry_date(self):
        expiry = self.cleaned_data.get("expiry_date")
        if expiry and expiry < timezone.localdate():
            raise ValidationError(
                "That expiry date has already passed. Check the packaging, or record it as "
                "expired stock instead."
            )
        return expiry

    def clean_received_on(self):
        received = self.cleaned_data.get("received_on")
        if received and received > timezone.localdate():
            raise ValidationError("The date received cannot be in the future.")
        return received

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        quantity = cleaned.get("quantity")
        if product and quantity and product.unit in WHOLE_UNITS:
            if quantity != quantity.to_integral_value():
                self.add_error(
                    "quantity",
                    f"{product.name} is counted in whole {product.get_unit_display().lower()}s.",
                )
        return cleaned


class AdjustStockForm(forms.Form):
    """Damaged, expired, missing, returned, or a counting correction."""

    product = ProductChoiceField(
        label="Product",
        queryset=Product.objects.none(),
        empty_label="Choose a product…",
        widget=forms.Select(attrs={**SELECT, "data-autofocus": "true"}),
    )
    movement_type = forms.ChoiceField(
        label="What happened?",
        choices=[(t.value, t.label) for t in ADJUSTMENT_TYPES],
        widget=forms.RadioSelect,
    )
    quantity = forms.DecimalField(
        label="Quantity",
        min_value=Decimal("0.001"),
        max_digits=14,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={
                **TEXT,
                "step": "0.001",
                "min": "0",
                "inputmode": "decimal",
                "data-preview-quantity": "true",
            }
        ),
        help_text="How many units this affects — always a positive number.",
    )
    batch = forms.ModelChoiceField(
        label="Which batch?",
        queryset=StockBatch.objects.none(),
        required=False,
        empty_label="Let the system choose (oldest expiry first)",
        widget=forms.Select(attrs=SELECT),
        help_text="Only needed if you know exactly which delivery this came from.",
    )
    reason = forms.CharField(
        label="Reason",
        max_length=200,
        widget=forms.TextInput(attrs={**TEXT, "placeholder": "e.g. Bottle broke during delivery"}),
        help_text="Required. In a few months this is what explains the change.",
    )
    notes = forms.CharField(
        label="Extra notes",
        required=False,
        widget=forms.Textarea(attrs={**TEXT, "rows": 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.select_related("category").order_by(
            "category__name", "name"
        )
        self.help_by_type = {t.value: ADJUSTMENT_HELP[t] for t in ADJUSTMENT_TYPES}

        product_id = self.data.get("product") or self.initial.get("product")
        if product_id:
            self.fields["batch"].queryset = (
                StockBatch.objects.filter(product_id=product_id, quantity_remaining__gt=0)
                .select_related("supplier")
                .fefo()
            )

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()
        if len(reason) < 3:
            raise ValidationError("Please write a short reason so this change makes sense later.")
        return reason

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        quantity = cleaned.get("quantity")
        movement_type = cleaned.get("movement_type")
        batch = cleaned.get("batch")

        if product and quantity and product.unit in WHOLE_UNITS:
            if quantity != quantity.to_integral_value():
                self.add_error(
                    "quantity",
                    f"{product.name} is counted in whole {product.get_unit_display().lower()}s.",
                )

        if batch and product and batch.product_id != product.pk:
            self.add_error("batch", "That batch belongs to a different product.")

        if product and quantity and movement_type and movement_type not in INCREASE_TYPES:
            available = batch.quantity_remaining if batch else product.stock_quantity
            if quantity > available:
                where = "that batch" if batch else "stock"
                self.add_error(
                    "quantity",
                    f"There is only {product.format_quantity(available)} in {where}. "
                    "Stock can never go below zero.",
                )
        return cleaned


class MovementFilterForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        empty_label="All products",
        widget=forms.Select(attrs={**SELECT, "data-auto-submit": "true"}),
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        empty_label="All categories",
        widget=forms.Select(attrs={**SELECT, "data-auto-submit": "true"}),
    )
    movement_type = forms.ChoiceField(
        required=False,
        choices=[("", "All change types")] + [(t.value, t.label) for t in MovementType],
        widget=forms.Select(attrs={**SELECT, "data-auto-submit": "true"}),
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(),
        required=False,
        empty_label="All suppliers",
        widget=forms.Select(attrs={**SELECT, "data-auto-submit": "true"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.order_by("name")
        self.fields["category"].queryset = Category.objects.order_by("name")
        self.fields["supplier"].queryset = Supplier.objects.order_by("name")
