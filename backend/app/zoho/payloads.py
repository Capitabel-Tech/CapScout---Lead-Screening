"""Turn our customers and meetings into Zoho Lead / Meeting (Events) records.

Until the Zoho admin creates the custom fields, only Zoho's standard fields can
be filled directly (see STANDARD_LEAD_MAP). Everything else is written, readably,
into the Description so no collected data is lost. As soon as a field has a Zoho
API name (field_definitions.zoho_api_name), it is sent into that field.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.fields.catalog import load_catalog
from app.models import Customer, Meeting

# Our field key -> Zoho standard Lead field.
STANDARD_LEAD_MAP: dict[str, str] = {
    "promoter": "Last_Name",
    "business_name": "Company",
    "mobile": "Mobile",
    "location": "City",
}

DESCRIPTION_LIMIT = 30000


def field_mapping(db_mapping: dict[str, str]) -> dict[str, str]:
    """Standard fields, overridden by whatever the Zoho admin has mapped in field_definitions."""
    return {**STANDARD_LEAD_MAP, **db_mapping}


def _typed(key: str, value: Any) -> Any:
    """Convert our stored text value to what a Zoho custom field expects."""
    spec = load_catalog().by_key.get(key)
    if spec and spec.field_type == "number":
        try:
            return float(Decimal(str(value)))
        except Exception:  # noqa: BLE001
            return value
    return value


BLOCK_START = "----- CapScout details (updated automatically) -----"
BLOCK_END = "----- end of CapScout details -----"
# Descriptions the app wrote itself before the block existed (safe to replace as a whole).
LEGACY_PREFIXES = ("Field Meeting CRM · MSME-", "CapScout · MSME-")


def lead_description(customer: Customer) -> str:
    """Readable snapshot of everything collected so far, inside a labelled block.

    Staff can write their own notes around the block; the app only ever rewrites the block.
    """
    vals = customer.current_values or {}
    lines = [BLOCK_START, customer.lead_ref, ""]
    for f in load_catalog().fields:
        if f.field_type == "system" or f.key not in vals:
            continue
        lines.append(f"{f.label}: {vals[f.key]}")
    lines.append(BLOCK_END)
    return "\n".join(lines)[:DESCRIPTION_LIMIT]


def merge_description(current: str | None, block: str) -> str | None:
    """The Lead's new Description after refreshing our block, or None to leave it alone.

    - empty Description: untouched (staff may have cleared it on purpose)
    - contains our block: only the block is replaced, everything around it is kept
    - an old unedited snapshot written by the app: replaced as a whole
    - anything else (staff removed the block and wrote their own text): untouched
    """
    if not current or not current.strip():
        return None
    a, b = current.find(BLOCK_START), current.find(BLOCK_END)
    if a != -1 and b > a:
        return current[:a] + block + current[b + len(BLOCK_END) :]
    if current.lstrip().startswith(LEGACY_PREFIXES):
        return block
    return None


def build_lead_payload(customer: Customer, mapping: dict[str, str], cfg: Settings) -> dict[str, Any]:
    vals = customer.current_values or {}
    payload: dict[str, Any] = {}
    for key, api_name in field_mapping(mapping).items():
        if key in vals:
            payload[api_name] = _typed(key, vals[key])
    # Last Name is mandatory in Zoho: never send a Lead without one.
    payload.setdefault("Last_Name", vals.get("business_name") or customer.lead_ref)
    payload["Description"] = lead_description(customer)
    if cfg.zoho_lead_ref_field:
        payload[cfg.zoho_lead_ref_field] = customer.lead_ref
    return payload


def event_title(meeting: Meeting, customer: Customer) -> str:
    vals = customer.current_values or {}
    who = vals.get("business_name") or vals.get("promoter") or ""
    return f"{customer.lead_ref} · Meeting #{meeting.sequence_no}" + (f" · {who}" if who else "")[:200]


def _iso(dt) -> str:
    return dt.replace(microsecond=0).isoformat()


def _maps_url(lat: Any, lng: Any) -> str:
    return f"https://www.google.com/maps?q={lat},{lng}"


def event_description(meeting: Meeting, customer: Customer, staff_name: str) -> str:
    labels = {f.key: f.label for f in load_catalog().fields}
    lines = [f"CapScout · {customer.lead_ref} · Meeting #{meeting.sequence_no}", f"Staff: {staff_name}"]
    if meeting.start_latitude is not None:
        acc = f" (±{round(float(meeting.start_accuracy_m))} m)" if meeting.start_accuracy_m is not None else ""
        lines.append(f"GPS at start: {_maps_url(meeting.start_latitude, meeting.start_longitude)}{acc}")
        if meeting.end_latitude is not None:
            lines.append(f"GPS at end: {_maps_url(meeting.end_latitude, meeting.end_longitude)}")
        if meeting.start_place:
            lines.append(f"Place: {meeting.start_place}")
    else:
        lines.append(f"GPS: not available ({meeting.gps_unavailable_reason or 'no reason given'})")
    lines.append("")
    if meeting.changes:
        lines.append("Collected / changed in this meeting:")
        for c in meeting.changes:
            label = labels.get(c["field"], c["field"])
            old, new = c.get("old"), c.get("new")
            if c.get("type") == "CLEARED":
                lines.append(f"- {label}: {old} → (cleared)")
            elif old:
                lines.append(f"- {label}: {old} → {new}")
            else:
                lines.append(f"- {label}: {new}")
    else:
        lines.append("No fields were changed in this meeting.")
    return "\n".join(lines)[:DESCRIPTION_LIMIT]


def build_event_payload(
    meeting: Meeting, customer: Customer, staff_name: str, cfg: Settings, lead_zoho_id: str | None
) -> dict[str, Any]:
    end = meeting.ended_at or (meeting.started_at + timedelta(minutes=15))
    payload: dict[str, Any] = {
        "Event_Title": event_title(meeting, customer)[:255],
        "Start_DateTime": _iso(meeting.started_at),
        "End_DateTime": _iso(end),
        "Meeting_Venue__s": cfg.zoho_meeting_venue,
        "Description": event_description(meeting, customer, staff_name),
    }
    if meeting.start_place:
        payload["Venue"] = meeting.start_place[:255]  # shows as the meeting's Location in Zoho
    if cfg.zoho_meeting_ref_field:
        payload[cfg.zoho_meeting_ref_field] = str(meeting.id)
    if lead_zoho_id:
        payload["$se_module"] = "Leads"
        payload["What_Id"] = {"id": lead_zoho_id}
    return payload


def escape_criteria(value: str) -> str:
    """Escape a value for use inside a Zoho search criteria (value)."""
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
