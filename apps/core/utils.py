from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.http import StreamingHttpResponse
from django.utils import timezone

ZERO = Decimal("0")
MONEY = Decimal("0.01")
QTY = Decimal("0.001")


def money(value) -> Decimal:
    """Quantise to 2dp using bankers-free rounding suitable for cash."""
    from decimal import ROUND_HALF_UP

    return (Decimal(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def quantity(value) -> Decimal:
    from decimal import ROUND_HALF_UP

    return (Decimal(value or 0)).quantize(QTY, rounding=ROUND_HALF_UP)


def format_money(value) -> str:
    return f"{settings.CURRENCY_SYMBOL}{money(value):,.2f}"


def parse_decimal(raw, default=None):
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, AttributeError, TypeError, ValueError):
        return default


def today() -> date:
    return timezone.localdate()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Aware [start, end) datetimes covering one local calendar day."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    return start, start + timedelta(days=1)


def range_bounds(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """Aware [start, end) datetimes covering an inclusive local date range."""
    start, _ = day_bounds(start_day)
    _, end = day_bounds(end_day)
    return start, end


def parse_date(raw, default=None):
    if not raw:
        return default
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return default


def resolve_period(request, default_days: int = 30) -> tuple[date, date, str]:
    """Read ?from=&to=&period= into an inclusive local date range.

    ``period`` accepts today / week / month / year / custom and always wins over
    explicit dates unless it is ``custom``.
    """
    now = today()
    period = (request.GET.get("period") or "").strip().lower()
    presets = {
        "today": (now, now),
        "week": (now - timedelta(days=now.weekday()), now),
        "month": (now.replace(day=1), now),
        "last30": (now - timedelta(days=29), now),
        "year": (now.replace(month=1, day=1), now),
    }
    if period in presets:
        start, end = presets[period]
        return start, end, period

    start = parse_date(request.GET.get("from"))
    end = parse_date(request.GET.get("to"))
    if start or end:
        start = start or (end - timedelta(days=default_days))
        end = end or now
        if end < start:
            start, end = end, start
        return start, end, "custom"

    return now - timedelta(days=default_days - 1), now, "last30"


class _Echo:
    def write(self, value):
        return value


def csv_response(filename: str, header: list[str], rows_iter) -> StreamingHttpResponse:
    """Stream a CSV so large exports never build a giant string in memory.

    A UTF-8 BOM is emitted first so Excel on Windows opens GH₵ correctly.
    """
    writer = csv.writer(_Echo())

    def generate():
        yield "﻿"
        yield writer.writerow(header)
        for row in rows_iter:
            yield writer.writerow(row)

    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    response = StreamingHttpResponse(generate(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}-{stamp}.csv"'
    response["Cache-Control"] = "no-store"
    return response


def page_range(page_obj, window: int = 2) -> list:
    """Compact pagination: 1 … 4 5 [6] 7 8 … 20."""
    paginator = page_obj.paginator
    current = page_obj.number
    last = paginator.num_pages
    if last <= 7 + window:
        return list(paginator.page_range)
    pages = {1, last, current}
    for offset in range(1, window + 1):
        pages.add(max(1, current - offset))
        pages.add(min(last, current + offset))
    ordered = sorted(pages)
    result = []
    previous = 0
    for number in ordered:
        if previous and number - previous > 1:
            result.append(None)
        result.append(number)
        previous = number
    return result
