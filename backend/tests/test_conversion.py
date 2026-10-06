from sqlalchemy import select

from app.models import AuditLog, Customer
from app.services.conversion import AlreadyLinkedElsewhere, lead_created, lead_creation_failed
from tests.test_meetings import _meeting, _new_lead, _post


def _lead(client, headers, **values):
    r = _new_lead(client, headers, values or {"promoter": "Ramesh Kumar", "mobile": "9876543210"})
    assert r.status_code == 201, r.text
    return r.json()["customer_id"]


def _tab(client, headers, tab):
    return [c["id"] for c in client.get(f"/api/customers?tab={tab}", headers=headers).json()["items"]]


def test_convert_request_waits_for_zoho_before_moving_tabs(client, make_staff, db):
    _, a = make_staff("A1")
    cid = _lead(client, a)

    r = client.post(f"/api/customers/{cid}/convert", headers=a)
    assert r.status_code == 200
    body = r.json()
    assert body["conversion_status"] == "CONVERTING"
    assert body["lead_sync_status"] == "PENDING"
    assert body["zoho_lead_id"] is None
    # Still in Not Converted until Zoho confirms the Lead.
    assert cid in _tab(client, a, "not_converted")
    assert cid not in _tab(client, a, "converted")
    assert db.scalar(select(AuditLog).where(AuditLog.action == "LEAD_CONVERSION_REQUESTED")) is not None

    # Zoho created the Lead (Phase 5 worker calls this).
    lead_created(db, db.get(Customer, cid), "ZL-1001")
    detail = client.get(f"/api/customers/{cid}", headers=a).json()
    assert detail["conversion_status"] == "CONVERTED"
    assert detail["zoho_lead_id"] == "ZL-1001"
    assert detail["converted_at"] is not None
    assert cid in _tab(client, a, "converted")
    assert cid not in _tab(client, a, "not_converted")


def test_conversion_keeps_customer_and_meeting_history(client, make_staff, db):
    _, a = make_staff("A1")
    cid = _lead(client, a)
    _post(client, a, cid, _meeting({"purpose": "LAP"}, started="2026-09-02T10:00:00+05:30"))
    client.post(f"/api/customers/{cid}/convert", headers=a)
    lead_created(db, db.get(Customer, cid), "ZL-2002")

    # Test 4: a meeting after conversion continues the same history.
    r = _post(client, a, cid, _meeting({"urgency": "Immediate"}, started="2026-09-03T10:00:00+05:30"))
    assert r.status_code == 201
    assert r.json()["sequence_no"] == 3
    history = client.get(f"/api/customers/{cid}/meetings", headers=a).json()["items"]
    assert [m["sequence_no"] for m in history] == [3, 2, 1]
    detail = client.get(f"/api/customers/{cid}", headers=a).json()
    assert detail["values"]["purpose"] == "LAP" and detail["values"]["urgency"] == "Immediate"
    assert client.get("/api/customers", headers=a).json()["total"] == 0  # not a second record
    assert client.get("/api/customers?tab=converted", headers=a).json()["total"] == 1


def test_convert_is_safe_to_repeat(client, make_staff, db):
    _, a = make_staff("A1")
    cid = _lead(client, a)
    client.post(f"/api/customers/{cid}/convert", headers=a)
    client.post(f"/api/customers/{cid}/convert", headers=a)
    requested = db.scalars(select(AuditLog).where(AuditLog.action == "LEAD_CONVERSION_REQUESTED")).all()
    assert len(requested) == 1

    lead_created(db, db.get(Customer, cid), "ZL-3003")
    r = client.post(f"/api/customers/{cid}/convert", headers=a)
    assert r.json()["conversion_status"] == "CONVERTED"
    assert r.json()["zoho_lead_id"] == "ZL-3003"


def test_failed_conversion_can_be_retried(client, make_staff, db):
    _, a = make_staff("A1")
    cid = _lead(client, a)
    client.post(f"/api/customers/{cid}/convert", headers=a)
    customer = db.get(Customer, cid)

    lead_creation_failed(db, customer, "Network unavailable", final=False)
    detail = client.get(f"/api/customers/{cid}", headers=a).json()
    assert detail["conversion_status"] == "CONVERTING"
    assert detail["lead_sync_status"] == "FAILED"

    lead_creation_failed(db, customer, "Zoho: INVALID_DATA", final=True)
    detail = client.get(f"/api/customers/{cid}", headers=a).json()
    assert detail["conversion_status"] == "CONVERSION_FAILED"
    assert detail["lead_sync_error"] == "Zoho: INVALID_DATA"
    assert cid in _tab(client, a, "not_converted")

    r = client.post(f"/api/customers/{cid}/convert", headers=a)
    assert r.json()["conversion_status"] == "CONVERTING"
    assert r.json()["lead_sync_error"] is None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "LEAD_CONVERSION_RETRIED")) is not None


def test_zoho_lead_id_cannot_belong_to_two_customers(client, make_staff, db):
    _, a = make_staff("A1")
    c1 = _lead(client, a, promoter="One")
    c2 = _lead(client, a, promoter="Two")
    for cid in (c1, c2):
        client.post(f"/api/customers/{cid}/convert", headers=a)
    lead_created(db, db.get(Customer, c1), "ZL-4004")
    try:
        lead_created(db, db.get(Customer, c2), "ZL-4004")
        raise AssertionError("expected AlreadyLinkedElsewhere")
    except AlreadyLinkedElsewhere:
        db.rollback()
    assert client.get(f"/api/customers/{c2}", headers=a).json()["conversion_status"] == "CONVERTING"


def test_staff_cannot_convert_someone_elses_customer(client, make_staff):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    cid = _lead(client, a)
    assert client.post(f"/api/customers/{cid}/convert", headers=b).status_code == 404
    assert client.get(f"/api/customers/{cid}", headers=a).json()["conversion_status"] == "NOT_CONVERTED"
