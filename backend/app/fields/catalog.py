"""The 44-field catalogue (from the client's Excel) and value validation.

V1 reads the catalogue from fields_v1.json, which scripts/extract_fields.py
generates from the Excel file. The same data is seeded into the
field_definitions table so a later version can make fields configurable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("fields_v1.json")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    excel_column: str
    position: int
    field_type: str
    options: tuple[str, ...] | None
    unit: str | None
    section: str
    display_order: int
    counts_toward_progress: bool
    system_source: str | None


@dataclass(frozen=True)
class Catalog:
    version: int
    sections: tuple[dict[str, Any], ...]
    fields: tuple[FieldSpec, ...]

    @property
    def by_key(self) -> dict[str, FieldSpec]:
        return {f.key: f for f in self.fields}

    @property
    def progress_total(self) -> int:
        return sum(f.counts_toward_progress for f in self.fields)


@lru_cache
def load_catalog() -> Catalog:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    fields = tuple(
        FieldSpec(
            key=f["key"],
            label=f["label"],
            excel_column=f["excel_column"],
            position=f["position"],
            field_type=f["field_type"],
            options=tuple(f["options"]) if f["options"] else None,
            unit=f["unit"],
            section=f["section"],
            display_order=f["display_order"],
            counts_toward_progress=f["counts_toward_progress"],
            system_source=f["system_source"],
        )
        for f in raw["fields"]
    )
    return Catalog(version=raw["version"], sections=tuple(raw["sections"]), fields=fields)


class FieldValueError(ValueError):
    def __init__(self, key: str, message: str):
        super().__init__(f"{key}: {message}")
        self.key = key
        self.message = message


MAX_TEXT = 200
MAX_LONG_TEXT = 2000


def normalize_mobile(raw: str) -> str | None:
    """Digits only, Indian country code / trunk zero stripped. None if not 10 digits."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def clean_value(key: str, value: Any) -> Any:
    """Validate a staff-entered value and return the canonical form to store.

    Returns None for an empty value (meaning "not collected").
    """
    spec = load_catalog().by_key.get(key)
    if spec is None:
        raise FieldValueError(key, "unknown field")
    if spec.field_type == "system":
        raise FieldValueError(key, "filled in by the app")
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None

    match spec.field_type:
        case "single_select":
            if value not in (spec.options or ()):
                raise FieldValueError(key, "not one of the allowed options")
            return value
        case "number":
            try:
                num = Decimal(str(value))
            except InvalidOperation:
                raise FieldValueError(key, "must be a number") from None
            if not num.is_finite() or num < 0:
                raise FieldValueError(key, "must be zero or more")
            # Stored as a string to keep exact decimals in JSONB.
            return format(num.normalize(), "f")
        case "date":
            try:
                return date.fromisoformat(str(value)).isoformat()
            except ValueError:
                raise FieldValueError(key, "must be a date (YYYY-MM-DD)") from None
        case "phone":
            mobile = normalize_mobile(str(value))
            if mobile is None:
                raise FieldValueError(key, "must be a 10-digit mobile number")
            return mobile
        case "text" | "long_text":
            if not isinstance(value, str):
                raise FieldValueError(key, "must be text")
            text = value.strip()
            limit = MAX_LONG_TEXT if spec.field_type == "long_text" else MAX_TEXT
            if len(text) > limit:
                raise FieldValueError(key, f"must be at most {limit} characters")
            return text
    raise FieldValueError(key, f"unsupported type {spec.field_type}")
