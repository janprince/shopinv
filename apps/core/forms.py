from __future__ import annotations

from django import forms

from .models import ShopSettings

TEXT = {"class": "form-control"}


class ShopSettingsForm(forms.ModelForm):
    class Meta:
        model = ShopSettings
        fields = [
            "shop_name",
            "tagline",
            "phone",
            "email",
            "address",
            "receipt_footer",
            "low_stock_threshold",
            "expiry_warning_days",
            "large_adjustment_threshold",
        ]
        labels = {
            "shop_name": "Shop name",
            "tagline": "Tagline",
            "phone": "Phone number",
            "email": "Email address",
            "address": "Shop address",
            "receipt_footer": "Message at the bottom of receipts",
            "low_stock_threshold": "Default low-stock level for new products",
            "expiry_warning_days": "Warn me this many days before expiry",
            "large_adjustment_threshold": "Ask for extra confirmation above this quantity",
        }
        help_texts = {
            "shop_name": "Shown in the app, on receipts and on the sign-in screen.",
            "address": "Printed on every receipt.",
            "expiry_warning_days": "Products expiring within this window appear on the dashboard.",
            "large_adjustment_threshold": "Protects against a slip of the keyboard on big write-offs.",
        }
        widgets = {
            "shop_name": forms.TextInput(attrs=TEXT),
            "tagline": forms.TextInput(attrs=TEXT),
            "phone": forms.TextInput(attrs={**TEXT, "inputmode": "tel"}),
            "email": forms.EmailInput(attrs=TEXT),
            "address": forms.Textarea(attrs={**TEXT, "rows": 3}),
            "receipt_footer": forms.TextInput(attrs=TEXT),
            "low_stock_threshold": forms.NumberInput(
                attrs={**TEXT, "min": "0", "inputmode": "numeric"}
            ),
            "expiry_warning_days": forms.NumberInput(
                attrs={**TEXT, "min": "1", "inputmode": "numeric"}
            ),
            "large_adjustment_threshold": forms.NumberInput(
                attrs={**TEXT, "min": "1", "step": "1", "inputmode": "numeric"}
            ),
        }
