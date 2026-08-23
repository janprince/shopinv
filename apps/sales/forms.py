from __future__ import annotations

import json
import uuid
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .models import PaymentMethod

TEXT = {"class": "form-control"}


class SaleForm(forms.Form):
    """The till's submission.

    The cart travels as JSON in a hidden field so a failed submission can be
    handed straight back to the shopkeeper with every line intact.
    """

    cart = forms.CharField(widget=forms.HiddenInput)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)
    payment_method = forms.ChoiceField(
        choices=PaymentMethod.choices, initial=PaymentMethod.CASH, widget=forms.RadioSelect
    )
    amount_received = forms.DecimalField(
        label="Cash received",
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={
                **TEXT,
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
                "id": "id_amount_received",
                "placeholder": "0.00",
            }
        ),
    )
    discount = forms.DecimalField(
        label="Discount",
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        initial=Decimal("0"),
        widget=forms.NumberInput(
            attrs={**TEXT, "step": "0.01", "min": "0", "inputmode": "decimal", "id": "id_discount"}
        ),
    )
    payment_reference = forms.CharField(
        label="Reference",
        required=False,
        max_length=60,
        widget=forms.TextInput(
            attrs={**TEXT, "placeholder": "Transaction ID", "id": "id_payment_reference"}
        ),
    )
    notes = forms.CharField(
        label="Note",
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={**TEXT, "placeholder": "Optional note about this sale"}),
    )

    def clean_cart(self):
        raw = self.cleaned_data["cart"]
        try:
            lines = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "The sale could not be read. Please add the items again."
            ) from exc
        if not isinstance(lines, list) or not lines:
            raise ValidationError("Add at least one product before completing the sale.")
        cleaned = []
        for line in lines:
            if not isinstance(line, dict):
                raise ValidationError("The sale could not be read. Please add the items again.")
            try:
                cleaned.append(
                    {
                        "product_id": int(line["product_id"]),
                        "quantity": Decimal(str(line["quantity"])),
                    }
                )
            except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                raise ValidationError("One of the items in the sale is not valid.") from exc
        return cleaned

    @staticmethod
    def fresh_key() -> str:
        return str(uuid.uuid4())


class ReverseSaleForm(forms.Form):
    reason = forms.CharField(
        label="Why is this sale being reversed?",
        max_length=300,
        widget=forms.Textarea(
            attrs={
                **TEXT,
                "rows": 3,
                "data-autofocus": "true",
                "placeholder": "e.g. Customer returned everything — wrong item sold",
            }
        ),
        help_text="This stays on the record permanently. Be specific.",
    )
    confirm = forms.BooleanField(
        label="I understand the items will go back into stock and this cannot be undone",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data["reason"] or "").strip()
        if len(reason) < 5:
            raise ValidationError("Please give a fuller reason (at least 5 characters).")
        return reason
