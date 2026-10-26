"""A reference to one object, `<type>:<key>` — the builder doors' form (ON-4), read in one place.

An action's object parameter takes one (`actions/executor.object_ref`), and Arc FA-2's subject of a question takes a list
of them (`agent/ask_subject`). Both read a reference here, so the two cannot come to disagree about what one names:
``"Order:O000123"``, ``{"object_type": "Order", "pk": "O000123"}``, or a bare key of the type the reader expects.
"""
from __future__ import annotations

import re
from typing import Any


def type_word(name: str) -> str:
    """A type's name with case and punctuation aside — `order_item`, `OrderItem` and `order item` name one type."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def same_type(a: str, b: str) -> bool:
    return type_word(a) == type_word(b)


def split_ref(value: Any, default_type: str = "") -> tuple[str, str]:
    """``(type, key)`` of a reference: ``"Type:key"``, ``{"object_type", "pk" | "key"}``, or a bare key, which is of
    ``default_type``. The key is "" when the reference names none; nothing is checked against an ontology here."""
    if isinstance(value, dict):
        typ, key = str(value.get("object_type") or default_type), value.get("pk", value.get("key"))
    else:
        text = str(value).strip()
        typ, sep, rest = text.partition(":")
        typ, key = (typ.strip(), rest.strip()) if sep else (default_type, text)
    return typ, "" if key is None else str(key).strip()
