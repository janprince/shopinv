"""Small helper around AuditEvent so call sites stay one line."""

from __future__ import annotations

import logging
from typing import Any

from .models import AuditAction, AuditEvent

logger = logging.getLogger("jcf.audit")


def client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record(
    action: str,
    *,
    summary: str,
    actor=None,
    request=None,
    obj: Any = None,
    object_label: str = "",
    details: dict | None = None,
) -> AuditEvent:
    """Write one audit row. Never raises into the caller's transaction path."""
    if actor is None and request is not None:
        candidate = getattr(request, "user", None)
        if candidate is not None and candidate.is_authenticated:
            actor = candidate

    object_type = object_id = ""
    if obj is not None:
        object_type = obj._meta.label_lower
        object_id = str(obj.pk)
        if not object_label:
            object_label = str(obj)[:200]

    event = AuditEvent(
        actor=actor,
        actor_label=getattr(actor, "display_name", "") or "",
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_label=object_label[:200],
        summary=summary[:300],
        details=details or {},
        ip_address=client_ip(request),
    )
    event.save()
    logger.info("audit %s by %s: %s", action, event.actor_label or "system", event.summary)
    return event


def snapshot(obj, fields) -> dict:
    """Capture field values BEFORE a ModelForm is validated.

    ``form.is_valid()`` writes the submitted data straight onto ``form.instance``,
    so a snapshot taken afterwards compares the object with itself and every audit
    diff comes out empty. Always call this before building the bound form.
    """
    return {name: getattr(obj, name) for name in fields}


def changed_fields(before: dict, after: dict, ignore: set[str] | None = None) -> dict:
    """Return {field: [old, new]} for values that actually differ."""
    ignore = ignore or set()
    diff = {}
    for key, new_value in after.items():
        if key in ignore:
            continue
        old_value = before.get(key)
        if str(old_value) != str(new_value):
            diff[key] = [_json_safe(old_value), _json_safe(new_value)]
    return diff


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


__all__ = ["AuditAction", "changed_fields", "client_ip", "record", "snapshot"]
