"""Zoho sync rules, tested against a FAKE Zoho (the real one is never contacted)."""

import asyncio
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import AuditLog, ConversionStatus, Customer, FieldDefinition, Meeting, SyncStatus
from app.zoho.client import McpZoho, ToolNotAllowed, ZohoError, ZohoUnavailable
from app.zoho.sync import claim_due_customers, claim_due_meetings, process, release_stale_claims
from tests.test_meetings import GPS_A, MEETING_1_VALUES, _meeting, _new_lead, _post


def _zf(api, label, dtype, req=False):
    return {"api_name": api, "display_label": label, "data_type": dtype, "system_mandatory": req,
            "view_type": {"create": True}, "pick_list_values": [], "length": 255, "visible": True}


# The Lead fields the fake Zoho reports (Zoho's standard ones).
STANDARD_ZOHO_FIELDS = [
    _zf("Company", "Company", "text"),
    _zf("Last_Name", "Last Name", "text", req=True),
    _zf("Mobile", "Mobile", "phone"),
    _zf("City", "Address - City", "text"),
    _zf("Description", "Description", "textarea"),
]


class FakeZoho:
    """Stands in for the Zoho MCP server: keeps records in memory and records every call."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.events: dict[str, dict] = {}
        self.leads: dict[str, dict] = {}
        self.fail = False  # every call raises (network down)
        self.fail_on: set[tuple[str, str]] = set()  # (tool, module) that raise ZohoError
        self.lose_reply_once = False  # next create stores the record but the reply is "lost"
        self._n = 1000

    def calls_to(self, tool, module=None):
        return [a for t, a in self.calls if t == tool and (module is None or a["path_variables"]["module"] == module)]

    def _new_id(self):
        self._n += 1
        return str(self._n)

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.fail:
            raise ZohoUnavailable("network down")
        if tool == "getFields":
            return {"data": {"fields": STANDARD_ZOHO_FIELDS}}
        if tool == "getRecord":
            zid = arguments["path_variables"]["recordId"]
            store = self.events if arguments["path_variables"]["module"] == "Events" else self.leads
            return {"data": {"data": [{"id": zid, **store[zid]}]}}
        module = arguments["path_variables"]["module"]
        if (tool, module) in self.fail_on:
            raise ZohoError(f"{tool}: INVALID_DATA refused", "INVALID_DATA")
        store = self.events if module == "Events" else self.leads
        ok = lambda zid: {"data": {"data": [{"code": "SUCCESS", "details": {"id": zid}}]}}  # noqa: E731

        if tool == "createRecords":
            rec = dict(arguments["body"]["data"][0])
            zid = self._new_id()
            store[zid] = rec
            if self.lose_reply_once:
                self.lose_reply_once = False
                raise ZohoUnavailable("timeout waiting for the reply")
            return ok(zid)
        if tool == "updateRecord":
            zid = arguments["path_variables"]["recordId"]
            store[zid].update(arguments["body"]["data"][0])
            return ok(zid)
        if tool == "updateRecords":
            out = []
            for item in arguments["body"]["data"]:
                store[item["id"]].update({k: v for k, v in item.items() if k != "id"})
                out.append({"code": "SUCCESS", "details": {"id": item["id"]}})
            return {"data": {"data": out}}
        if tool == "searchRecords":
            m = re.match(r"\((\w+):equals:(.*)\)$", arguments["query_params"]["criteria"])
            field, value = m.group(1), m.group(2).replace("\\(", "(").replace("\\)", ")")
            hits = [{"id": zid} for zid, r in store.items() if r.get(field) == value]
            return {"data": {"data": hits}} if hits else {}
        raise AssertionError(f"unexpected tool {tool}")


def run(fake: FakeZoho) -> None:
    """One worker pass: claim what is due, then sync it against the fake."""
    cfg, factory = get_settings(), get_sessionmaker()
    with factory() as db:
        customers, meetings = claim_due_customers(db), claim_due_meetings(db)
    asyncio.run(process(factory, fake, cfg, customers, meetings))


def _setup_lead(client, headers, **extra):
    r = _new_lead(client, headers, {"promoter": "Ramesh Kumar", "business_name": "RK Traders", "mobile": "9876543210", **extra})
    assert r.status_code == 201, r.text
    return r.json()["customer_id"], r.json()["meeting"]["id"]


def _customer(db, cid) -> Customer:
    db.expire_all()
    return db.get(Customer, cid)


def _meeting_row(db, mid) -> Meeting:
    db.expire_all()
    return db.get(Meeting, mid)


# --- Not converted: Zoho Meetings yes, Zoho Lead NO ---------------------------------------------


def test_unconverted_meeting_goes_to_zoho_meetings_without_a_lead(client, make_staff, db):
    _, a = make_staff("A1")
    cid, mid = _setup_lead(client, a)
    fake = FakeZoho()
    run(fake)

    assert fake.calls_to("createRecords", "Leads") == []  # NO Lead before conversion
    assert len(fake.events) == 1
    event = next(iter(fake.events.values()))
    assert "What_Id" not in event
    assert event["Event_Title"] == "MSME-0001 · Meeting #1 · RK Traders"
    assert event["Meeting_Venue__s"] == "Client location"
    # Same moment the staff member started the meeting, with an explicit UTC offset Zoho accepts.
    assert datetime.fromisoformat(event["Start_DateTime"]) == datetime.fromisoformat("2026-09-01T10:00:00+05:30")
    assert datetime.fromisoformat(event["End_DateTime"]) == datetime.fromisoformat("2026-09-01T10:25:00+05:30")

    m = _meeting_row(db, mid)
    assert m.zoho_sync_status == SyncStatus.SYNCED and m.zoho_meeting_id in fake.events
    assert _customer(db, cid).zoho_lead_id is None


def test_event_description_has_staff_gps_and_changes(client, make_staff, db):
    _, a = make_staff("A1")
    _setup_lead(client, a, loan_required="25")
    fake = FakeZoho()
    run(fake)
    desc = next(iter(fake.events.values()))["Description"]
    assert "Staff: Staff A1" in desc
    assert "https://www.google.com/maps?q=17.385044,78.486671" in desc
    assert "- Loan Required (₹): 25" in desc


def test_no_gps_reason_is_sent(client, make_staff, db):
    _, a = make_staff("A1")
    body = {"meeting": _meeting({"promoter": "X"}, gps=None, reason="Permission denied")}
    assert client.post("/api/leads/new", json=body, headers=a).status_code == 201
    fake = FakeZoho()
    run(fake)
    assert "GPS: not available (Permission denied)" in next(iter(fake.events.values()))["Description"]


# --- Conversion ------------------------------------------------------------------------------------


def test_conversion_creates_lead_links_old_meetings_and_moves_tab(client, make_staff, db):
    _, a = make_staff("A1")
    cid, mid = _setup_lead(client, a)
    _post(client, a, cid, _meeting({"purpose": "Expansion"}, started="2026-09-02T10:00:00+05:30"))
    fake = FakeZoho()
    run(fake)  # both meetings -> Zoho, still no Lead
    assert len(fake.events) == 2 and not fake.leads

    client.post(f"/api/customers/{cid}/convert", headers=a)
    run(fake)

    assert len(fake.leads) == 1
    lead_id, lead = next(iter(fake.leads.items()))
    assert lead["Last_Name"] == "Ramesh Kumar" and lead["Company"] == "RK Traders" and lead["Mobile"] == "9876543210"
    assert "Purpose: Expansion" in lead["Description"]
    for event in fake.events.values():  # both earlier meetings now linked to the Lead
        assert event["What_Id"] == {"id": lead_id} and event["$se_module"] == "Leads"
    c = _customer(db, cid)
    assert c.conversion_status == ConversionStatus.CONVERTED and c.zoho_lead_id == lead_id
    assert cid in [i["id"] for i in client.get("/api/customers?tab=converted", headers=a).json()["items"]]
    assert client.get(f"/api/customers/{cid}", headers=a).json()["zoho_lead_id"] == lead_id


def test_meeting_after_conversion_is_linked_and_updates_the_lead(client, make_staff, db):
    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a)
    fake = FakeZoho()
    run(fake)
    client.post(f"/api/customers/{cid}/convert", headers=a)
    run(fake)
    lead_id = next(iter(fake.leads))

    r = _post(client, a, cid, _meeting({"monthly_banking": "45", "business_name": "RK Traders Pvt Ltd"}, started="2026-09-03T10:00:00+05:30"))
    assert r.status_code == 201
    run(fake)

    new_event = next(e for e in fake.events.values() if "Meeting #2" in e["Event_Title"])
    assert new_event["What_Id"] == {"id": lead_id} and new_event["$se_module"] == "Leads"
    assert fake.leads[lead_id]["Company"] == "RK Traders Pvt Ltd"  # the mapped field this meeting changed
    update = fake.calls_to("updateRecord", "Leads")[-1]["body"]["data"][0]
    # The mapped field this meeting changed, plus the app's own Description block. Nothing else.
    assert set(update) == {"Company", "Description"} and update["Company"] == "RK Traders Pvt Ltd"
    assert "Business Name: RK Traders Pvt Ltd" in update["Description"] and "Monthly Banking (₹): 45" in update["Description"]
    assert len(fake.leads) == 1  # updated, never duplicated


def test_mapped_custom_field_is_sent_as_a_number(client, make_staff, db):
    _, a = make_staff("A1")
    db.execute(update(FieldDefinition).where(FieldDefinition.key == "loan_required").values(zoho_api_name="Loan_Required"))
    db.commit()
    try:
        cid, _ = _setup_lead(client, a, loan_required="25.5")
        client.post(f"/api/customers/{cid}/convert", headers=a)
        fake = FakeZoho()
        run(fake)
        assert next(iter(fake.leads.values()))["Loan_Required"] == 25.5
    finally:
        db.execute(update(FieldDefinition).where(FieldDefinition.key == "loan_required").values(zoho_api_name=None))
        db.commit()


# --- Failures, retries, duplicates --------------------------------------------------------------------


def test_failed_sync_keeps_the_meeting_and_retries_later(client, make_staff, db):
    _, a = make_staff("A1")
    cid, mid = _setup_lead(client, a)
    fake = FakeZoho()
    fake.fail = True
    run(fake)

    m = _meeting_row(db, mid)
    assert m.zoho_sync_status == SyncStatus.FAILED and m.zoho_attempts == 1
    assert "network down" in m.zoho_last_error and m.zoho_meeting_id is None
    assert m.zoho_next_attempt_at > datetime.now(UTC)  # waits before the next try
    assert client.get(f"/api/customers/{cid}/meetings", headers=a).json()["items"][0]["zoho_sync_status"] == "FAILED"
    run(fake)  # not due yet -> nothing happens
    assert _meeting_row(db, mid).zoho_attempts == 1

    fake.fail = False
    db.execute(update(Meeting).where(Meeting.id == mid).values(zoho_next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    run(fake)
    m = _meeting_row(db, mid)
    assert m.zoho_sync_status == SyncStatus.SYNCED and m.zoho_last_error is None and len(fake.events) == 1
    actions = [r.action for r in db.scalars(select(AuditLog).where(AuditLog.action.like("ZOHO_SYNC%")))]
    assert "ZOHO_SYNC_MEETING_FAILED" in actions and "ZOHO_SYNC_MEETING_OK" in actions


def test_lost_reply_does_not_create_a_duplicate_meeting(client, make_staff, db):
    _, a = make_staff("A1")
    _, mid = _setup_lead(client, a)
    fake = FakeZoho()
    fake.lose_reply_once = True  # Zoho CREATED the meeting but we never saw the answer
    run(fake)
    assert _meeting_row(db, mid).zoho_sync_status == SyncStatus.FAILED and len(fake.events) == 1

    db.execute(update(Meeting).where(Meeting.id == mid).values(zoho_next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    run(fake)
    m = _meeting_row(db, mid)
    assert m.zoho_sync_status == SyncStatus.SYNCED
    assert len(fake.events) == 1 and len(fake.calls_to("createRecords", "Events")) == 1  # found by search, not re-created
    assert m.zoho_meeting_id in fake.events


def test_zoho_id_is_saved_even_if_a_later_step_fails(client, make_staff, db):
    _, a = make_staff("A1")
    cid, mid = _setup_lead(client, a)
    fake = FakeZoho()
    run(fake)
    client.post(f"/api/customers/{cid}/convert", headers=a)
    run(fake)
    # Next meeting: the Event is created, but updating the Lead fails.
    _post(client, a, cid, _meeting({"business_name": "RK Traders Pvt Ltd"}, started="2026-09-03T10:00:00+05:30"))
    fake.fail_on = {("updateRecord", "Leads")}
    run(fake)
    m2 = db.scalars(select(Meeting).where(Meeting.sequence_no == 2)).one()
    db.expire_all()
    assert m2.zoho_sync_status == SyncStatus.FAILED and m2.zoho_meeting_id is not None  # id kept
    n_events = len(fake.events)

    fake.fail_on = set()
    db.execute(update(Meeting).where(Meeting.id == m2.id).values(zoho_next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    run(fake)
    db.expire_all()
    assert db.get(Meeting, m2.id).zoho_sync_status == SyncStatus.SYNCED
    assert len(fake.events) == n_events  # no second Event


def test_gives_up_then_manual_retry_works(client, make_staff, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "zoho_max_attempts", 1)
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    cid, mid = _setup_lead(client, a)
    fake = FakeZoho()
    fake.fail = True
    run(fake)
    m = _meeting_row(db, mid)
    assert m.zoho_sync_status == SyncStatus.FAILED and m.zoho_next_attempt_at is None  # no more automatic tries

    fake.fail = False
    run(fake)
    assert _meeting_row(db, mid).zoho_sync_status == SyncStatus.FAILED  # still waiting for the button

    assert client.post(f"/api/customers/{cid}/meetings/{mid}/retry-sync", headers=b).status_code == 404  # not B's meeting
    r = client.post(f"/api/customers/{cid}/meetings/{mid}/retry-sync", headers=a)
    assert r.status_code == 200 and r.json()["zoho_sync_status"] == "PENDING"
    run(fake)
    assert _meeting_row(db, mid).zoho_sync_status == SyncStatus.SYNCED


def test_failed_conversion_can_be_retried_with_the_button(client, make_staff, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "zoho_max_attempts", 1)
    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a)
    fake = FakeZoho()
    run(fake)
    client.post(f"/api/customers/{cid}/convert", headers=a)
    fake.fail_on = {("createRecords", "Leads")}
    run(fake)

    c = _customer(db, cid)
    assert c.conversion_status == ConversionStatus.CONVERSION_FAILED and "INVALID_DATA" in c.zoho_last_error
    assert c.zoho_lead_id is None and not fake.leads

    fake.fail_on = set()
    client.post(f"/api/customers/{cid}/convert", headers=a)  # "Retry conversion"
    run(fake)
    c = _customer(db, cid)
    assert c.conversion_status == ConversionStatus.CONVERTED and len(fake.leads) == 1


def test_conversion_retry_after_lead_created_does_not_create_a_second_lead(client, make_staff, db):
    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a)
    fake = FakeZoho()
    run(fake)
    client.post(f"/api/customers/{cid}/convert", headers=a)
    fake.fail_on = {("updateRecords", "Events")}  # Lead is created, then linking meetings fails
    run(fake)
    c = _customer(db, cid)
    assert c.zoho_lead_id is not None and c.conversion_status == ConversionStatus.CONVERTING  # id kept

    fake.fail_on = set()
    db.execute(update(Customer).where(Customer.id == cid).values(zoho_next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    run(fake)
    assert len(fake.leads) == 1 and len(fake.calls_to("createRecords", "Leads")) == 1
    assert _customer(db, cid).conversion_status == ConversionStatus.CONVERTED


# --- Safety ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["deleteRecord", "deleteRecords", "updateUser", "createFields", "upsertRecords"])
def test_only_allowed_tools_can_be_called(tool):
    zoho = McpZoho("https://example.invalid/mcp/abcdefghijklmnopqrstuvwxyz/message", 1)
    with pytest.raises(ToolNotAllowed):
        asyncio.run(zoho.call(tool, {}))


def test_secret_url_is_scrubbed_from_errors():
    url = "https://zoho-test.invalid/mcp/0123456789abcdef0123456789abcdef/message"

    async def go():
        async with McpZoho(url, 2):
            pass

    with pytest.raises(ZohoUnavailable) as e:
        asyncio.run(go())
    assert "0123456789abcdef0123456789abcdef" not in str(e.value) and "zoho-test.invalid" not in str(e.value)


def test_items_left_half_done_by_a_restart_are_retried_immediately(client, make_staff, db):
    _, a = make_staff("A1")
    cid, mid = _setup_lead(client, a)
    with get_sessionmaker()() as s:
        assert len(claim_due_meetings(s)) == 1  # claimed by a pass that then "crashes": now SYNCING, 10 min lease
    m = _meeting_row(db, mid)
    assert m.zoho_sync_status == SyncStatus.SYNCING and m.zoho_next_attempt_at > datetime.now(UTC)

    fake = FakeZoho()
    run(fake)  # lease not expired -> still untouched
    assert not fake.events

    with get_sessionmaker()() as s:  # the backend restarts
        assert release_stale_claims(s) == 1
    run(fake)
    assert _meeting_row(db, mid).zoho_sync_status == SyncStatus.SYNCED and len(fake.events) == 1


def test_plain_text_answers_from_zoho_are_reported_as_errors():
    """Zoho answers some failures with plain text, e.g. 'Connection not authorised'."""
    from types import SimpleNamespace

    class Session:
        async def call_tool(self, name, arguments):
            return SimpleNamespace(
                is_error=False,
                content=[SimpleNamespace(text="You cannot perform this operation. Connection not authorised")],
            )

    zoho = McpZoho("https://example.invalid/mcp/abcdefghijklmnopqrstuvwxyz/message", 5)
    zoho._session = Session()
    with pytest.raises(ZohoError) as e:
        asyncio.run(zoho.call("createRecords", {"path_variables": {"module": "Events"}, "body": {"data": []}}))
    assert e.value.code == "NOT_AUTHORISED" and "Connection not authorised" in str(e.value)


def test_description_block_refresh_keeps_text_staff_wrote_around_it():
    from app.zoho.payloads import BLOCK_END, BLOCK_START, merge_description

    new_block = f"{BLOCK_START}\nMSME-0001\n\nLoan Required (₹): 60\n{BLOCK_END}"
    old_block = f"{BLOCK_START}\nMSME-0001\n\nLoan Required (₹): 50\n{BLOCK_END}"
    # staff notes before and after the block survive; only the block changes
    merged = merge_description(f"Called twice.\n\n{old_block}\n\nFollow up Friday.", new_block)
    assert merged == f"Called twice.\n\n{new_block}\n\nFollow up Friday."
    # a Description staff cleared on purpose is not refilled
    assert merge_description(None, new_block) is None and merge_description("  ", new_block) is None
    # an old unedited snapshot written by the app is replaced whole
    assert merge_description("Field Meeting CRM · MSME-0005\n\nLoan Required (₹): 50", new_block) == new_block
    # staff removed the block and wrote their own text: leave it alone
    assert merge_description("Only my own notes", new_block) is None
