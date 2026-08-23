from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower
from django.utils import timezone

from .models import WHOLE_UNITS, Category, Product, Supplier, Unit

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


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description", "is_active"]
        labels = {"name": "Category name", "is_active": "Show this category when adding products"}
        help_texts = {
            "description": "A short note so everyone uses this category the same way.",
        }
        widgets = {
            "name": forms.TextInput(attrs={**TEXT, "placeholder": "e.g. Honey & syrups"}),
            "description": forms.TextInput(attrs=TEXT),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_name(self):
        name = (self.cleaned_data["name"] or "").strip()
        clash = Category.objects.annotate(n=Lower("name")).filter(n=name.lower())
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("A category with that name already exists.")
        return name


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "phone", "email", "location", "notes", "is_active"]
        labels = {"name": "Supplier name", "is_active": "Still supplying us"}
        help_texts = {
            "phone": "For example 024 123 4567 or +233 24 123 4567.",
            "notes": "Delivery days, minimum order, who to ask for — anything useful.",
        }
        widgets = {
            "name": forms.TextInput(attrs={**TEXT, "placeholder": "e.g. Kwahu Farms"}),
            "phone": forms.TextInput(
                attrs={**TEXT, "inputmode": "tel", "placeholder": "024 123 4567"}
            ),
            "email": forms.EmailInput(attrs=TEXT),
            "location": forms.TextInput(attrs={**TEXT, "placeholder": "e.g. Madina, Accra"}),
            "notes": forms.Textarea(attrs={**TEXT, "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_name(self):
        name = (self.cleaned_data["name"] or "").strip()
        clash = Supplier.objects.annotate(n=Lower("name")).filter(n=name.lower())
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("A supplier with that name already exists.")
        return name


class ProductForm(forms.ModelForm):
    """Product details. Opening stock is handled separately, by a movement."""

    opening_quantity = forms.DecimalField(
        label="Opening stock",
        required=False,
        min_value=Decimal("0"),
        max_digits=14,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={**TEXT, "step": "0.001", "min": "0", "inputmode": "decimal"}
        ),
        help_text="How much you have on the shelf right now. Leave blank if none.",
    )
    opening_expiry = forms.DateField(
        label="Expiry date of that stock",
        required=False,
        widget=HtmlDateInput(),
        help_text="Only if this product expires.",
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "sku",
            "category",
            "unit",
            "description",
            "cost_price",
            "selling_price",
            "minimum_stock",
            "barcode",
            "is_active",
        ]
        labels = {
            "name": "Product name",
            "sku": "Product code (SKU)",
            "unit": "Sold by",
            "cost_price": "Cost price",
            "selling_price": "Selling price",
            "minimum_stock": "Warn me below",
            "is_active": "Available to sell",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={**TEXT, "placeholder": "e.g. Raw Shea Butter 250g", "data-autofocus": "true"}
            ),
            "sku": forms.TextInput(
                attrs={**TEXT, "placeholder": "e.g. SHEA-250", "autocapitalize": "characters"}
            ),
            "category": forms.Select(attrs=SELECT),
            "unit": forms.Select(attrs=SELECT),
            "description": forms.Textarea(attrs={**TEXT, "rows": 2}),
            "cost_price": forms.NumberInput(
                attrs={**TEXT, "step": "0.01", "min": "0", "inputmode": "decimal"}
            ),
            "selling_price": forms.NumberInput(
                attrs={**TEXT, "step": "0.01", "min": "0", "inputmode": "decimal"}
            ),
            "minimum_stock": forms.NumberInput(
                attrs={**TEXT, "step": "0.001", "min": "0", "inputmode": "decimal"}
            ),
            "barcode": forms.TextInput(
                attrs={**TEXT, "inputmode": "numeric", "placeholder": "Scan or type"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.active().order_by("name")
        self.fields["category"].empty_label = "Choose a category…"
        if self.instance.pk:
            # Stock is only ever changed by receiving or adjusting it.
            del self.fields["opening_quantity"]
            del self.fields["opening_expiry"]

    def clean_sku(self):
        sku = (self.cleaned_data.get("sku") or "").strip().upper()
        if not sku:
            # Optional. Products without a code are found by name at the till.
            return ""
        clash = Product.objects.filter(sku__iexact=sku)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError(
                f"The code {sku} is already used by another product. Product codes must be unique."
            )
        return sku

    def clean_barcode(self):
        barcode = (self.cleaned_data.get("barcode") or "").strip()
        if not barcode:
            return ""
        clash = Product.objects.filter(barcode__iexact=barcode)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("Another product already uses that barcode.")
        return barcode

    def clean_opening_expiry(self):
        expiry = self.cleaned_data.get("opening_expiry")
        if expiry and expiry < timezone.localdate():
            raise ValidationError("That date has already passed. Use a stock adjustment instead.")
        return expiry

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get("unit")
        quantity = cleaned.get("opening_quantity")

        if unit in WHOLE_UNITS and quantity and quantity != quantity.to_integral_value():
            self.add_error(
                "opening_quantity",
                f"{Unit(unit).label} is counted in whole numbers. Enter a whole number.",
            )

        cost = cleaned.get("cost_price")
        price = cleaned.get("selling_price")
        if cost is not None and price is not None and price < cost:
            # A loss-making price is unusual but legitimate (clearance), so warn, don't block.
            self.selling_below_cost = True
        return cleaned


class ProductFilterForm(forms.Form):
    """Kept deliberately loose — a bad filter value should never 500 the list."""

    q = forms.CharField(required=False)
    category = forms.IntegerField(required=False)
    stock = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All stock levels"),
            ("in", "In stock"),
            ("low", "Low stock"),
            ("out", "Out of stock"),
            ("restock", "Needs restocking"),
        ],
    )
    expiry = forms.ChoiceField(
        required=False,
        choices=[("", "Any expiry"), ("expiring", "Expiring soon"), ("expired", "Expired")],
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "Active products"), ("all", "All"), ("inactive", "Inactive only")],
    )
    sort = forms.CharField(required=False)
