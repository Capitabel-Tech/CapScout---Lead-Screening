"""Background worker: every few seconds, sync whatever is due to Zoho.

It runs in a daemon thread inside the backend process. Work is claimed in the
database with row locks (FOR UPDATE SKIP LOCKED), so even if several backend
processes run, no meeting or conversion is handled twice at the same time.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.services.places import resolve_pending
from app.zoho.client import McpZoho
from app.zoho.sync import claim_due_customers, claim_due_meetings, process, release_stale_claims

log = logging.getLogger("zoho.worker")


def run_once(cfg: Settings, force_zoho: bool = False) -> int:
    """One pass. Returns how many items were handled (0 = nothing was due).

    Order matters: places are worked out first, so a meeting sent to Zoho in the same pass
    already carries its place.
    """
    factory = get_sessionmaker()
    handled = 0
    if cfg.geocoding_enabled:
        with factory() as db:
            handled += resolve_pending(db, cfg)

    zoho_on = bool(cfg.zoho_mcp_url) and (cfg.zoho_sync_enabled or force_zoho)
    if not zoho_on:
        return handled
    with factory() as db:
        customer_ids = claim_due_customers(db)
        meeting_ids = claim_due_meetings(db)
    if not (customer_ids or meeting_ids):
        return handled

    async def go() -> None:
        async with McpZoho(cfg.zoho_mcp_url or "", cfg.zoho_call_timeout_seconds) as zoho:
            await process(factory, zoho, cfg, customer_ids, meeting_ids)

    try:
        asyncio.run(go())
    except Exception as e:  # noqa: BLE001 - e.g. cannot connect: put the claimed work back for a retry
        log.warning("Zoho pass failed before any item completed: %s", e)
        _release(customer_ids, meeting_ids, str(e))
    return handled + len(customer_ids) + len(meeting_ids)


def _release(customer_ids, meeting_ids, error: str) -> None:
    """Connection-level failure: record it against each claimed item so it retries with backoff."""
    from app.models import Customer, Meeting, SyncStatus
    from app.zoho.sync import _now, retry_delay

    cfg = get_settings()
    with get_sessionmaker()() as db:
        for cid in customer_ids:
            c = db.get(Customer, cid)
            if c and c.zoho_sync_status == SyncStatus.SYNCING:
                c.zoho_attempts += 1
                c.zoho_sync_status = SyncStatus.FAILED
                c.zoho_last_error = error[:2000]
                c.zoho_next_attempt_at = _now() + retry_delay(c.zoho_attempts)
        for mid in meeting_ids:
            m = db.get(Meeting, mid)
            if m and m.zoho_sync_status == SyncStatus.SYNCING:
                m.zoho_attempts += 1
                m.zoho_sync_status = SyncStatus.FAILED
                m.zoho_last_error = error[:2000]
                final = m.zoho_attempts >= cfg.zoho_max_attempts
                m.zoho_next_attempt_at = None if final else _now() + retry_delay(m.zoho_attempts)
        db.commit()


class SyncWorker:
    def __init__(self, cfg: Settings):
        self._cfg = cfg
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="zoho-sync", daemon=True)

    def start(self) -> None:
        try:
            with get_sessionmaker()() as db:
                n = release_stale_claims(db)
            if n:
                log.info("Zoho sync: %s unfinished item(s) from before the restart will be retried now", n)
        except Exception:  # noqa: BLE001 - never block startup
            log.exception("could not release unfinished sync items")
        log.info("Zoho sync worker started")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                busy = run_once(self._cfg) > 0
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("sync pass crashed")
                busy = False
            self._stop.wait(0.5 if busy else self._cfg.zoho_poll_seconds)
