"""GPS numbers -> readable places.

Rules:
  * every meeting records its OWN place, worked out from its own GPS
  * the lead's Location (address) is never typed: it is set ONCE, from the first meeting that has a
    GPS place, and then stays fixed (later meetings never change it)

The lookup runs in the background worker, never while a staff member is saving, so a slow or failing
map service can never block or lose a meeting. If it fails, the meeting keeps its coordinates and
map link, and the lookup is retried a few times.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Customer, Meeting
from app.services.customers import apply_values

log = logging.getLogger("places")

Lookup = Callable[[Settings, float, float], Any]

# OpenStreetMap asks for at most one request per second, and for results to be cached.
MIN_GAP_SECONDS = 1.1
_throttle_lock = threading.Lock()
_last_request = 0.0
_CACHE_MAX = 500
_cache: OrderedDict[tuple[float, float], dict[str, str | None]] = OrderedDict()
_NOTHING: dict[str, str | None] = {"place": None, "area": None}


# In Indian map data, "neighbourhood" is often a municipal ward ("Ward 99") and "suburb" a zone
# ("Zone 8 Anna Nagar"). Those numbers mean nothing to staff, so they are skipped or stripped.
_ADMIN_ONLY = re.compile(r"^(ward|zone|division|circle|sector|block)\b[\s\d.\-]*$", re.I)  # "Ward 99", "Sector 4"
_ADMIN_PREFIX = re.compile(r"^(ward|zone|division|circle)\s*\d+\s*[-:]?\s*", re.I)


def _clean(name: str | None) -> str | None:
    if not name:
        return None
    name = _ADMIN_PREFIX.sub("", name).strip()
    return None if not name or _ADMIN_ONLY.match(name) else name


def _city(a: dict[str, Any]) -> str | None:
    return a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("state_district")


def _locality(a: dict[str, Any]) -> str | None:
    """The area people know, e.g. "Anna Nagar West", not an administrative ward or zone number."""
    road = a.get("road") or a.get("pedestrian") or a.get("residential")
    if road and "," in road:  # often "2nd Avenue, Anna Nagar West": the locality follows the street
        tail = _clean(road.split(",", 1)[1].strip())
        if tail:
            return tail
    for key in ("neighbourhood", "suburb", "quarter", "city_district"):
        cleaned = _clean(a.get(key))
        if cleaned:
            return cleaned
    return None


def _join(parts: list[str | None]) -> str:
    """Join non-empty parts, skipping any already contained in an earlier part (no repeats)."""
    out: list[str] = []
    for part in parts:
        if part and not any(part.lower() in earlier.lower() for earlier in out):
            out.append(part)
    return ", ".join(out)


def build_place_name(data: dict[str, Any]) -> str | None:
    """A readable place from a Nominatim answer, e.g. "2nd Avenue, Anna Nagar West, Chennai, Tamil Nadu"."""
    a = data.get("address") or {}
    street = a.get("road") or a.get("pedestrian") or a.get("residential")
    text = _join([street, _locality(a), _city(a), a.get("state")])
    if text:
        return text[:200]
    name = data.get("display_name")
    return name[:200] if name else None


def build_area_name(data: dict[str, Any]) -> str | None:
    """A short "Area, city" used as the lead's Location, e.g. "Anna Nagar West, Chennai"."""
    a = data.get("address") or {}
    text = _join([_locality(a) or a.get("road"), _city(a)])
    if text:
        return text[:120]
    return build_place_name(data)


def nominatim_data(cfg: Settings, latitude: float, longitude: float) -> dict[str, Any] | None:
    """One polite request to the map service (never faster than its rate limit)."""
    global _last_request
    with _throttle_lock:
        wait = MIN_GAP_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
    response = httpx.get(
        cfg.geocoding_url,
        params={
            "format": "jsonv2",
            "lat": f"{latitude:.6f}",
            "lon": f"{longitude:.6f}",
            "zoom": 18,
            "addressdetails": 1,
            "accept-language": "en",
        },
        headers={"User-Agent": cfg.geocoding_user_agent},
        timeout=cfg.geocoding_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("error"):
        return None
    return data


def names_for(cfg: Settings, latitude: float, longitude: float) -> dict[str, str | None]:
    """{"place": full readable place, "area": short "Area, city"} for a GPS position.

    Cached (positions within about 10 m share an answer), as the map service's policy requires.
    Never raises: a failed lookup returns nothing.
    """
    key = (round(latitude, 4), round(longitude, 4))
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    try:
        data = nominatim_data(cfg, latitude, longitude)
    except Exception as e:  # noqa: BLE001
        log.warning("place lookup failed: %s", e)
        return dict(_NOTHING)
    if not data:
        return dict(_NOTHING)
    result = {"place": build_place_name(data), "area": build_area_name(data)}
    _cache[key] = result  # only real answers are cached; a failure may succeed next time
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return result


def _as_names(result: Any) -> dict[str, str | None]:
    if isinstance(result, dict):
        return {"place": result.get("place"), "area": result.get("area") or result.get("place")}
    if isinstance(result, str) and result:
        return {"place": result, "area": result}
    return dict(_NOTHING)


def _set_lead_location_once(db: Session, meeting: Meeting, area: str) -> None:
    """The lead's address = where its first GPS-located meeting happened. Set once, never changed."""
    db.execute(select(Customer.id).where(Customer.id == meeting.customer_id).with_for_update())
    customer = db.get(Customer, meeting.customer_id)
    db.refresh(customer)
    if (customer.current_values or {}).get("location"):
        return
    changes = apply_values(customer, {"location": area})
    meeting.changes = [*(meeting.changes or []), *changes]  # part of this meeting's history


def resolve_pending(db: Session, cfg: Settings, lookup: Lookup | None = None, limit: int = 10) -> int:
    """Work out the place for meetings that have GPS but no place yet. Returns how many were tried."""
    lookup = lookup or names_for
    rows = db.scalars(
        select(Meeting)
        .where(
            Meeting.start_latitude.is_not(None),
            Meeting.start_place.is_(None),
            Meeting.place_attempts < cfg.geocoding_max_attempts,
        )
        .order_by(Meeting.created_at)
        .limit(limit)
    ).all()
    for meeting in rows:
        names = dict(_NOTHING)
        try:
            names = _as_names(lookup(cfg, float(meeting.start_latitude), float(meeting.start_longitude)))
        except Exception as e:  # noqa: BLE001 - a failed lookup must never affect the meeting
            log.warning("place lookup failed for meeting %s: %s", meeting.id, e)
        meeting.place_attempts += 1
        if names["place"]:
            meeting.start_place = names["place"]
            _set_lead_location_once(db, meeting, names["area"] or names["place"])
        db.commit()
    return len(rows)
