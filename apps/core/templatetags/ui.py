"""Presentation helpers shared by every template."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.core.utils import money as to_money

register = template.Library()

# --------------------------------------------------------------------------------------
# Icons — a small hand-picked line set. Inline SVG keeps the app to zero icon requests.
# --------------------------------------------------------------------------------------
_PATHS = {
    "dashboard": '<path d="M3 12h7V3H3zM14 21h7v-9h-7zM14 8h7V3h-7zM3 21h7v-5H3z"/>',
    "cart": '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/>'
    '<path d="M2 3h2.2l2.5 12.2a2 2 0 0 0 2 1.6h8.4a2 2 0 0 0 2-1.55L21 8H6"/>',
    "box": '<path d="M21 8.5v7L12 21l-9-5.5v-7L12 3z"/><path d="M3.3 7.8 12 12.5l8.7-4.7M12 12.5V21"/>',
    "layers": '<path d="M12 3 2.5 8 12 13l9.5-5z"/><path d="m2.5 12.5 9.5 5 9.5-5"/>',
    "receipt": '<path d="M5 3v18l2.5-1.5L10 21l2-1.5L14 21l2.5-1.5L19 21V3z"/><path d="M8.5 8h7M8.5 12h7M8.5 16h4"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M7 15V9M12 17V6M17 17v-4"/>',
    "truck": '<path d="M3 6h11v9H3z"/><path d="M14 9h3.5L21 12.5V15h-7z"/><circle cx="7" cy="18" r="1.6"/><circle cx="17.5" cy="18" r="1.6"/>',
    "users": '<circle cx="9" cy="8" r="3.2"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M17 5.2a3.2 3.2 0 0 1 0 5.6M17.5 14.2A6 6 0 0 1 21.5 20"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v2.2M12 19.3v2.2M4.2 4.2l1.6 1.6M18.2 18.2l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.2 19.8l1.6-1.6M18.2 5.8l1.6-1.6"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-3.6-3.6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "check": '<path d="m4.5 12.5 5 5L20 7"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "alert": '<path d="M12 3.5 1.8 20.5h20.4z"/><path d="M12 10v4.2M12 17.6v.1"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.3l3.4 2"/>',
    "arrow-up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "arrow-down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "arrow-left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "download": '<path d="M12 3v12M7 11l5 5 5-5"/><path d="M4 20h16"/>',
    "printer": '<path d="M7 8V3h10v5"/><path d="M5 8h14a2 2 0 0 1 2 2v6h-4v5H7v-5H3v-6a2 2 0 0 1 2-2z"/>',
    "menu": '<path d="M3 6h18M3 12h18M3 18h18"/>',
    "logout": '<path d="M14 3h5a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1h-5"/><path d="M10 8 6 12l4 4M6 12h11"/>',
    "leaf": '<path d="M4 20c0-9 6-15 16-15 0 10-5 15-11 15a5 5 0 0 1-5-5z"/><path d="M9.5 14.5 18 6"/>',
    "wallet": '<path d="M3 7a2 2 0 0 1 2-2h12v4"/><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9H5a2 2 0 0 1-2-2z"/><circle cx="16.5" cy="14" r="1.2"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 8v4.5l3 1.8"/>',
    "edit": '<path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17z"/><path d="M14.5 5.5l4 4"/>',
    "eye": '<path d="M1.8 12S5.6 5.5 12 5.5 22.2 12 22.2 12 18.4 18.5 12 18.5 1.8 12 1.8 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M9.9 5.8A9.6 9.6 0 0 1 12 5.5c6.4 0 10.2 6.5 10.2 6.5a17 17 0 0 1-3.4 4.1M6.4 7.6A16.7 16.7 0 0 0 1.8 12S5.6 18.5 12 18.5a9.5 9.5 0 0 0 3.8-.8"/><path d="M3 3l18 18"/><path d="M10 10a3 3 0 0 0 4 4"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.1"/>',
    "shield": '<path d="M12 2.5 20 6v6c0 5-3.4 8.4-8 9.5-4.6-1.1-8-4.5-8-9.5V6z"/><path d="m8.5 12 2.4 2.4 4.6-4.8"/>',
    "wifi-off": '<path d="M3 3l18 18"/><path d="M9 15.5a4 4 0 0 1 5.1-.4M5.5 12.2a9 9 0 0 1 3.2-2M2 8.8A14 14 0 0 1 7 6M13 5.2a14 14 0 0 1 9 3.6M15.6 11.9a9 9 0 0 1 2.5 1.6"/><circle cx="12" cy="19" r="1"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "tag": '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.4"/>',
}


@register.simple_tag
def icon(name: str, size: int = 18, cls: str = "") -> str:
    path = _PATHS.get(name)
    if path is None:
        return ""
    return format_html(
        '<svg class="icon {}" width="{}" height="{}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true" focusable="false">{}</svg>',
        cls,
        size,
        size,
        mark_safe(path),  # noqa: S308 - fixed internal path data
    )


# --------------------------------------------------------------------------------------
# Money & numbers
# --------------------------------------------------------------------------------------
@register.filter
def cedis(value) -> str:
    """GH₵1,234.50 — the only way money should ever be printed."""
    try:
        amount = to_money(value)
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    return f"{settings.CURRENCY_SYMBOL}{amount:,.2f}"


@register.filter
def cedis_plain(value) -> str:
    try:
        return f"{to_money(value):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "0.00"


@register.filter
def qty(value) -> str:
    """Trim trailing zeros so 3.000 reads as 3 and 1.500 as 1.5."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "0"
    text = f"{number:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@register.filter
def percent_of(value, total):
    try:
        total = Decimal(str(total))
        if not total:
            return Decimal("0")
        return (Decimal(str(value)) / total) * 100
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


# --------------------------------------------------------------------------------------
# Query-string helpers for filters, sorting and pagination
# --------------------------------------------------------------------------------------
@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs) -> str:
    """Rebuild the current query string with some keys replaced or dropped."""
    request = context["request"]
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    if "page" not in kwargs:
        params.pop("page", None)
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag(takes_context=True)
def query_page(context, page_number) -> str:
    request = context["request"]
    params = request.GET.copy()
    params["page"] = page_number
    return f"?{params.urlencode()}"


# --------------------------------------------------------------------------------------
# Status badges
# --------------------------------------------------------------------------------------
_STOCK_BADGE = {
    "in": ("badge-in", "In stock"),
    "low": ("badge-low", "Low stock"),
    "out": ("badge-out", "Out of stock"),
}
_EXPIRY_BADGE = {
    "expired": ("badge-out", "Expired"),
    "expiring": ("badge-warn", "Expiring soon"),
}


@register.simple_tag
def stock_badge(product) -> str:
    css, label = _STOCK_BADGE[product.stock_status]
    return format_html('<span class="badge-status {}">{}</span>', css, label)


@register.simple_tag
def expiry_badge(state) -> str:
    if state not in _EXPIRY_BADGE:
        return ""
    css, label = _EXPIRY_BADGE[state]
    return format_html('<span class="badge-status {}">{}</span>', css, label)


@register.simple_tag
def active_badge(is_active) -> str:
    if is_active:
        return ""
    return format_html('<span class="badge-status badge-muted">Inactive</span>')


#: A sale is the routine case and must not look like a caution; losses should.
_MOVEMENT_BADGE = {
    "opening": "badge-in",
    "received": "badge-in",
    "return": "badge-in",
    "correction_up": "badge-in",
    "sale_reversal": "badge-info",
    "sale": "badge-muted",
    "damaged": "badge-out",
    "expired": "badge-out",
    "missing": "badge-out",
    "correction_down": "badge-warn",
}


@register.simple_tag
def movement_badge(movement) -> str:
    css = _MOVEMENT_BADGE.get(movement.movement_type, "badge-muted")
    return format_html(
        '<span class="badge-status {} badge-square">{}</span>',
        css,
        movement.get_movement_type_display(),
    )


@register.simple_tag
def sale_status_badge(sale) -> str:
    if sale.status == "reversed":
        return format_html('<span class="badge-status badge-out">Reversed</span>')
    return format_html('<span class="badge-status badge-in">Completed</span>')


@register.filter
def get_item(mapping, key):
    """Look up a dict value by a variable key inside a template."""
    if mapping is None:
        return ""
    try:
        return mapping.get(key, "")
    except AttributeError:
        return ""


@register.simple_tag
def nav_active(request, *url_prefixes) -> str:
    path = request.path
    return "is-active" if any(path.startswith(p) for p in url_prefixes) else ""
