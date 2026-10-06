"""The "Convert to Lead" form: the Zoho Lead form, read live from Zoho.

The fields, their labels, types and dropdown choices come from Zoho itself (getFields), so the
form always looks like the Lead form in the client's Zoho CRM, and any field the Zoho admin adds
later appears here automatically. Values are pre-filled from what the app already collected,
and everything the staff member confirms is validated against Zoho's own rules before it is saved.
"""

from __future__ import annotations

import re
import time
from typing import Any

from app.config import Settings
from app.fields.catalog import load_catalog
from app.models import Customer
from app.zoho.client import McpZoho
from app.zoho.payloads import STANDARD_LEAD_MAP, lead_description

# Zoho fields that make no sense to type by hand on a phone.
EXCLUDE = {"Owner", "Latitude", "Longitude", "Record_Image"}

# Zoho data_type -> the kind of input the app shows.
KINDS = {
    "text": "text",
    "textarea": "textarea",
    "picklist": "select",
    "email": "email",
    "phone": "phone",
    "website": "url",
    "integer": "integer",
    "bigint": "integer",
    "double": "decimal",
    "decimal": "decimal",
    "currency": "decimal",
    "boolean": "boolean",
    "date": "date",
}

HUGE_LIST = 300  # e.g. State has ~4000 choices: shown as a typed box, Zoho checks it
CACHE_SECONDS = 600
_cache: dict[str, Any] = {"at": 0.0, "fields": None}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def parse_fields(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only what the create form shows, in a compact shape."""
    out: list[dict[str, Any]] = []
    for f in raw:
        api = f.get("api_name")
        kind = KINDS.get(f.get("data_type", ""))
        view = f.get("view_type") or {}
        if (
            not api
            or api in EXCLUDE
            or kind is None
            or not view.get("create")
            or f.get("read_only")
            or f.get("field_read_only")
            or f.get("visible") is False
        ):
            continue
        options: list[str] | None = None
        if kind == "select":
            values = [
                v.get("actual_value") or v.get("display_value")
                for v in f.get("pick_list_values") or []
                if (v.get("actual_value") or v.get("display_value")) not in (None, "", "-None-")
            ]
            if len(values) > HUGE_LIST:
                kind = "text"  # too long to list; typed instead
            else:
                options = values
        out.append(
            {
                "api_name": api,
                "label": f.get("display_label") or f.get("field_label") or api,
                "kind": kind,
                "required": bool(f.get("system_mandatory")),
                "options": options,
                "max_length": f.get("length") if kind in ("text", "textarea", "phone", "email", "url") else None,
                "custom": bool(f.get("custom_field")),
            }
        )
    return out


async def load_lead_fields(cfg: Settings, zoho: Any = None, force: bool = False) -> list[dict[str, Any]]:
    """The Zoho Lead create-form fields (cached for a few minutes).

    Uses the given Zoho client when there is one (the sync worker already has a connection open).
    """
    if not force and _cache["fields"] is not None and time.monotonic() - _cache["at"] < CACHE_SECONDS:
        return _cache["fields"]
    args = {"query_params": {"module": "Leads", "type": "all"}}
    if zoho is not None:
        res = await zoho.call("getFields", args)
    else:
        async with McpZoho(cfg.zoho_mcp_url or "", cfg.zoho_call_timeout_seconds) as own:
            res = await own.call("getFields", args)
    raw = (res.get("data") or {}).get("fields") or res.get("fields") or []
    fields = parse_fields(raw)
    if not fields:
        raise RuntimeError("Zoho returned no Lead fields")
    _cache.update(at=time.monotonic(), fields=fields)
    return fields


# --- one value ------------------------------------------------------------------------------


def coerce(field: dict[str, Any], raw: Any) -> tuple[Any, str | None]:
    """Turn what the user typed into what Zoho expects. Returns (value, error)."""
    kind = field["kind"]
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None, None
    text = str(raw).strip()
    try:
        if kind in ("text", "textarea", "phone", "url"):
            limit = field.get("max_length")
            if limit and len(text) > limit:
                return None, f"at most {limit} characters"
            return text, None
        if kind == "email":
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
                return None, "enter a valid email address"
            return text, None
        if kind == "integer":
            return int(float(text)), None
        if kind == "decimal":
            return float(text), None
        if kind == "date":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                return None, "enter a date (YYYY-MM-DD)"
            return text, None
        if kind == "boolean":
            if text.lower() in ("true", "yes", "1"):
                return True, None
            if text.lower() in ("false", "no", "0"):
                return False, None
            return None, "choose Yes or No"
        if kind == "select":
            for opt in field.get("options") or []:
                if opt.lower() == text.lower():
                    return opt, None
            return None, "choose one of the options"
    except ValueError:
        return None, "enter a valid number"
    return text, None


# --- the form -----------------------------------------------------------------------------------


def prefill(
    fields: list[dict[str, Any]], customer: Customer, db_mapping: dict[str, str]
) -> dict[str, tuple[Any, str]]:
    """What the app already knows, as {zoho_api_name: (value, where_it_came_from)}.

    Order of precedence: the standard fields, fields the admin mapped explicitly, then any
    Zoho field whose label is exactly the label of one of our 44 fields (so fields created
    with the Excel names fill themselves). A value is only used if it is valid for that field.
    """
    by_api = {f["api_name"]: f for f in fields}
    ours = customer.current_values or {}
    labels = {f.key: f.label for f in load_catalog().fields if f.field_type != "system"}
    out: dict[str, tuple[Any, str]] = {}

    def put(api: str, raw: Any, source: str) -> None:
        field = by_api.get(api)
        if field is None or api in out or raw in (None, ""):
            return
        value, error = coerce(field, raw)
        if error is None and value is not None:
            out[api] = (value, source)

    for key, api in {**STANDARD_LEAD_MAP, **db_mapping}.items():
        put(api, ours.get(key), labels.get(key, key))
    by_label = {_norm(label): key for key, label in labels.items()}
    for f in fields:
        key = by_label.get(_norm(f["label"]))
        if key:
            put(f["api_name"], ours.get(key), labels[key])
    if "Last_Name" in by_api and "Last_Name" not in out:
        put("Last_Name", ours.get("business_name") or customer.lead_ref, "Business Name")
    if "Description" in by_api and "Description" not in out:
        put("Description", lead_description(customer), "everything collected in the app")
    return out


def update_payload(
    fields: list[dict[str, Any]], meeting: Any, customer: Customer, db_mapping: dict[str, str]
) -> dict[str, Any]:
    """Zoho Lead fields to update after a meeting: ONLY the mapped fields this meeting changed.

    Never the whole Lead: the staff member confirmed the Lead's details on the Convert form, and a
    later meeting must not overwrite what was edited there.
    """
    by_api = {f["api_name"]: f for f in fields}
    labels = {f.key: f.label for f in load_catalog().fields if f.field_type != "system"}
    key_to_api = {**STANDARD_LEAD_MAP, **db_mapping}
    by_label = {_norm(label): key for key, label in labels.items()}
    for f in fields:
        key = by_label.get(_norm(f["label"]))
        if key:
            key_to_api.setdefault(key, f["api_name"])
    values = customer.current_values or {}
    payload: dict[str, Any] = {}
    for change in meeting.changes or []:
        key = change["field"]
        field = by_api.get(key_to_api.get(key, ""))
        if field is None or change.get("type") == "CLEARED" or key not in values:
            continue
        value, error = coerce(field, values[key])
        if error is None and value is not None:
            payload[field["api_name"]] = value
    return payload


def build_form(
    fields: list[dict[str, Any]], customer: Customer, db_mapping: dict[str, str]
) -> list[dict[str, Any]]:
    filled = prefill(fields, customer, db_mapping)
    form = []
    for f in fields:
        value, source = filled.get(f["api_name"], (None, None))
        form.append({**f, "value": value, "prefilled_from": source})
    return form


def validate(fields: list[dict[str, Any]], values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Check the confirmed form against Zoho's rules. Returns (clean_values, errors)."""
    by_api = {f["api_name"]: f for f in fields}
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for api, raw in values.items():
        field = by_api.get(api)
        if field is None:
            continue  # not a field of the Zoho Lead form: ignored
        value, error = coerce(field, raw)
        if error:
            errors[api] = error
        elif value is not None:
            clean[api] = value
    for f in fields:
        if f["required"] and f["api_name"] not in clean and f["api_name"] not in errors:
            errors[f["api_name"]] = "required"
    return clean, errors
