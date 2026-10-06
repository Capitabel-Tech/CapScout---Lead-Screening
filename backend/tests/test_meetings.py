import uuid
from datetime import UTC, datetime, timedelta

GPS_A = {"latitude": 17.385044, "longitude": 78.486671, "accuracy_m": 12.5, "captured_at": "2026-09-01T10:00:05+05:30"}
GPS_B = {"latitude": 17.440081, "longitude": 78.348915, "accuracy_m": 30, "captured_at": "2026-09-03T11:00:05+05:30"}

# 15 fields for meeting 1 (Test 1 in the brief).
MEETING_1_VALUES = {
    "source_type": "DSA",
    "source_name": "Sri Finance",
    "business_name": "RK Traders",
    "promoter": "Ramesh Kumar",
    "mobile": "9876543210",
    "potential_lender": "Axis Bank",
    "constitution": "Proprietorship",
    "industry": "Textiles",
    "vintage_years": "6",
    "loan_required": "25",
    "purpose": "Working Capital",
    "urgency": "<30 days",
    "secured_unsecured": "Open to both",
    "annual_turnover": "180",
    "monthly_banking": "40",
}


def _new_customer(client, headers, **values):
    values = values or {"promoter": "Ramesh Kumar"}
    r = client.post("/api/customers", json={"values": values}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _meeting(values, *, gps=GPS_A, reason=None, started="2026-09-01T10:00:00+05:30", mid=None, **extra):
    started_dt = datetime.fromisoformat(started)
    body = {
        "id": str(mid or uuid.uuid4()),
        "started_at": started,
        "ended_at": (started_dt + timedelta(minutes=25)).isoformat(),
        "values": values,
        **extra,
    }
    if gps:
        body["gps_start"] = gps
    if reason:
        body["gps_unavailable_reason"] = reason
    return body


def _post(client, headers, cid, body):
    return client.post(f"/api/customers/{cid}/meetings", json=body, headers=headers)


def test_first_and_second_meeting_build_current_state_and_keep_history(client, make_staff):
    _, a = make_staff("A1")
    cid = _new_customer(client, a)

    # Meeting 1: 15 fields (promoter already set at creation -> 14 new, 0 updated).
    r = _post(client, a, cid, _meeting(MEETING_1_VALUES))
    assert r.status_code == 201, r.text
    m1 = r.json()
    assert m1["sequence_no"] == 1
    assert m1["gps_status"] == "CAPTURED"
    assert m1["gps_start"]["latitude"] == GPS_A["latitude"]
    assert m1["zoho_sync_status"] == "PENDING"
    assert m1["staff"]["full_name"] == "Staff A1"
    assert len(m1["changes"]) == 14
    assert all(c["type"] == "NEW" for c in m1["changes"])

    # Meeting 2: 8 new fields + 2 existing fields updated (Test 2).
    m2_values = {
        "monthly_surplus": "6",
        "existing_debt": "10",
        "monthly_emi": "0.8",
        "gst_available": "Yes",
        "itr_financials": "Yes",
        "bank_statements": "Unknown",
        "documents_readiness": "Partial",
        "next_action_date": "2026-10-10",
        "monthly_banking": "45",  # update 40 -> 45
        "potential_lender": "HDFC Bank",  # update
        "industry": "Textiles",  # unchanged: not recorded as a change
    }
    r = _post(client, a, cid, _meeting(m2_values, gps=GPS_B, started="2026-09-03T11:00:00+05:30"))
    assert r.status_code == 201, r.text
    m2 = r.json()
    assert m2["sequence_no"] == 2
    types = {c["field"]: c["type"] for c in m2["changes"]}
    assert sum(t == "NEW" for t in types.values()) == 8
    assert types["monthly_banking"] == "UPDATED" and types["potential_lender"] == "UPDATED"
    assert "industry" not in types
    banking = next(c for c in m2["changes"] if c["field"] == "monthly_banking")
    assert (banking["old"], banking["new"]) == ("40", "45")

    # Current state has the latest values.
    detail = client.get(f"/api/customers/{cid}", headers=a).json()
    assert detail["values"]["monthly_banking"] == "45"
    assert detail["values"]["potential_lender"] == "HDFC Bank"
    assert detail["progress"]["filled"] == 23  # 15 + 8, of 41
    assert detail["meeting_count"] == 2
    assert detail["conversion_status"] == "NOT_CONVERTED"
    assert detail["zoho_lead_id"] is None  # no Zoho Lead before conversion

    # History is unchanged: meeting 1 still says 40.
    history = client.get(f"/api/customers/{cid}/meetings", headers=a).json()["items"]
    assert [m["sequence_no"] for m in history] == [2, 1]
    m1_banking = next(c for c in history[1]["changes"] if c["field"] == "monthly_banking")
    assert m1_banking["new"] == "40"
    assert history[1]["gps_start"]["latitude"] == GPS_A["latitude"]
    assert history[0]["gps_start"]["latitude"] == GPS_B["latitude"]


def test_retrying_the_same_meeting_does_not_duplicate(client, make_staff):
    _, a = make_staff("A1")
    cid = _new_customer(client, a)
    body = _meeting({"purpose": "LAP"})
    assert _post(client, a, cid, body).status_code == 201
    again = _post(client, a, cid, body)
    assert again.status_code == 200
    assert again.json()["sequence_no"] == 1
    assert client.get(f"/api/customers/{cid}", headers=a).json()["meeting_count"] == 1
    assert len(client.get(f"/api/customers/{cid}/meetings", headers=a).json()["items"]) == 1


def test_meeting_id_cannot_be_reused_for_another_customer(client, make_staff):
    _, a = make_staff("A1")
    c1 = _new_customer(client, a, promoter="One")
    c2 = _new_customer(client, a, promoter="Two")
    mid = uuid.uuid4()
    assert _post(client, a, c1, _meeting({"purpose": "LAP"}, mid=mid)).status_code == 201
    r = _post(client, a, c2, _meeting({"purpose": "LAP"}, mid=mid))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "MEETING_ID_CONFLICT"


def test_gps_or_reason_is_required_and_never_faked(client, make_staff):
    _, a = make_staff("A1")
    cid = _new_customer(client, a)
    assert _post(client, a, cid, _meeting({}, gps=None)).status_code == 422
    assert _post(client, a, cid, _meeting({}, gps=None, reason="   ")).status_code == 422

    r = _post(client, a, cid, _meeting({"purpose": "LAP"}, gps=None, reason="Permission denied"))
    assert r.status_code == 201
    m = r.json()
    assert m["gps_status"] == "UNAVAILABLE"
    assert m["gps_unavailable_reason"] == "Permission denied"
    assert m["gps_start"] is None


def test_rejects_impossible_gps_and_times(client, make_staff):
    _, a = make_staff("A1")
    cid = _new_customer(client, a)
    bad_gps = {**GPS_A, "latitude": 123}
    assert _post(client, a, cid, _meeting({}, gps=bad_gps)).status_code == 422
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert _post(client, a, cid, _meeting({}, started=future)).status_code == 422
    body = _meeting({})
    body["ended_at"] = "2026-09-01T09:00:00+05:30"  # before start
    assert _post(client, a, cid, body).status_code == 422


def test_invalid_field_values_save_nothing(client, make_staff):
    _, a = make_staff("A1")
    cid = _new_customer(client, a)
    r = _post(client, a, cid, _meeting({"purpose": "Holiday", "loan_required": "20"}))
    assert r.status_code == 422
    assert "purpose" in r.json()["detail"]["errors"]
    detail = client.get(f"/api/customers/{cid}", headers=a).json()
    assert detail["meeting_count"] == 0
    assert "loan_required" not in detail["values"]


def test_clearing_a_wrong_value(client, make_staff):
    _, a = make_staff("A1")
    cid = _new_customer(client, a)
    _post(client, a, cid, _meeting({"industry": "Textile", "purpose": "LAP"}))
    r = _post(client, a, cid, _meeting({"industry": ""}, started="2026-09-02T10:00:00+05:30"))
    assert r.json()["changes"] == [{"field": "industry", "old": "Textile", "new": None, "type": "CLEARED"}]
    detail = client.get(f"/api/customers/{cid}", headers=a).json()
    assert "industry" not in detail["values"]
    assert detail["progress"]["filled"] == 2  # promoter + purpose


def test_staff_cannot_add_or_see_meetings_of_others(client, make_staff):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    cid = _new_customer(client, a)
    _post(client, a, cid, _meeting({"purpose": "LAP"}))
    assert client.get(f"/api/customers/{cid}/meetings", headers=b).status_code == 404
    assert _post(client, b, cid, _meeting({"purpose": "Capex"})).status_code == 404
    assert client.get(f"/api/customers/{cid}", headers=a).json()["values"]["purpose"] == "LAP"


def test_meeting_records_who_conducted_it(client, make_staff):
    staff, a = make_staff("A1")
    cid = _new_customer(client, a)
    m = _post(client, a, cid, _meeting({"purpose": "LAP"})).json()
    assert m["staff"]["id"] == str(staff.id)


def test_changing_mobile_to_another_staffs_customer_is_blocked(client, make_staff):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    _new_customer(client, b, promoter="Theirs", mobile="9000000002")
    cid = _new_customer(client, a, promoter="Mine", mobile="9000000001")
    r = _post(client, a, cid, _meeting({"mobile": "+91 90000 00002", "purpose": "LAP"}))
    assert r.status_code == 409
    assert r.json()["detail"]["message"] == "This customer is already assigned to another staff member."
    detail = client.get(f"/api/customers/{cid}", headers=a).json()
    assert detail["values"]["mobile"] == "9000000001"
    assert detail["meeting_count"] == 0


# --- "New lead": prospect + Meeting #1 in one step (prototype flow) -----------


def _new_lead(client, headers, values, **extra):
    return client.post("/api/leads/new", json={"meeting": _meeting(values), **extra}, headers=headers)


def test_new_lead_creates_prospect_and_meeting_one(client, make_staff):
    _, a = make_staff("A1")
    r = _new_lead(client, a, MEETING_1_VALUES)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["meeting"]["sequence_no"] == 1
    assert len(body["meeting"]["changes"]) == 15  # every value belongs to Meeting #1's history
    detail = client.get(f"/api/customers/{body['customer_id']}", headers=a).json()
    assert detail["progress"]["filled"] == 15
    assert detail["meeting_count"] == 1
    assert detail["conversion_status"] == "NOT_CONVERTED"
    assert detail["zoho_lead_id"] is None


def test_new_lead_retry_returns_same_records(client, make_staff):
    _, a = make_staff("A1")
    body = {"meeting": _meeting({"promoter": "Ramesh", "mobile": "9876543210"})}
    first = client.post("/api/leads/new", json=body, headers=a)
    again = client.post("/api/leads/new", json=body, headers=a)
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["customer_id"] == again.json()["customer_id"]
    assert client.get("/api/customers", headers=a).json()["total"] == 1


def test_new_lead_needs_identity_and_valid_values(client, make_staff):
    _, a = make_staff("A1")
    assert _new_lead(client, a, {"purpose": "LAP"}).status_code == 422
    assert _new_lead(client, a, {"promoter": "X", "next_action": "Call promoter"}).status_code == 422  # not an Excel option
    assert client.get("/api/customers", headers=a).json()["total"] == 0


def test_new_lead_duplicate_rules(client, make_staff):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    _new_lead(client, b, {"promoter": "Theirs", "mobile": "9000000002"})
    r = _new_lead(client, a, {"promoter": "Mine", "mobile": "9000000002"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNED_TO_OTHER_STAFF"

    first = _new_lead(client, a, {"promoter": "Ramesh", "mobile": "9000000001", "purpose": "LAP"}).json()
    r = _new_lead(client, a, {"promoter": "Ramesh K", "mobile": "9000000001"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DUPLICATE_OWN"

    # Overwrite: the new meeting becomes Meeting #2 of the existing customer.
    r = _new_lead(
        client, a, {"promoter": "Ramesh K", "mobile": "9000000001", "urgency": "Immediate"},
        on_duplicate="overwrite", overwrite_customer_id=first["customer_id"],
    )
    assert r.status_code == 201
    assert r.json()["customer_id"] == first["customer_id"]
    assert r.json()["meeting"]["sequence_no"] == 2
    detail = client.get(f"/api/customers/{first['customer_id']}", headers=a).json()
    assert detail["values"]["promoter"] == "Ramesh K" and detail["values"]["purpose"] == "LAP"


def test_status_and_litigation_are_free_text_next_action_uses_excel_options(client, make_staff):
    _, a = make_staff("A1")
    r = _new_lead(
        client, a,
        {"promoter": "X", "status": "Met owner, positive", "litigation_dispute": "None known",
         "next_action": "Documents Pending", "next_action_date": "2026-10-08"},
    )
    assert r.status_code == 201, r.text
    card = client.get("/api/customers", headers=a).json()["items"][0]
    assert card["status"] == "Met owner, positive"
    assert card["next_action"] == "Documents Pending"
    assert card["next_action_date"] == "2026-10-08"


def test_home_summary_counts(client, make_staff):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    _new_lead(client, a, {"promoter": "One"})
    _new_lead(client, a, {"promoter": "Two"})
    _new_lead(client, b, {"promoter": "Other staff"})
    s = client.get("/api/customers/-/summary", headers=a).json()
    assert s == {"not_converted": 2, "converted": 0, "sync_pending": 2, "sync_failed": 0}


def test_only_the_promoters_mobile_counts_as_a_duplicate_not_the_source_contact(client, make_staff):
    """Same phone number = the Mobile field (the customer). Source Contact is the referrer's number."""
    _, a = make_staff("A1")
    first = _new_lead(client, a, {"promoter": "Charan", "mobile": "9875435211"})
    assert first.status_code == 201

    # A different customer referred by someone whose Source Contact equals Charan's mobile: NOT a duplicate.
    r = _new_lead(client, a, {"promoter": "Pragya", "mobile": "9000000011", "source_contact": "9875435211"})
    assert r.status_code == 201, r.text

    # Another referral from the same source with the same Source Contact is also fine.
    r = _new_lead(client, a, {"promoter": "Third", "mobile": "9000000012", "source_contact": "9875435211"})
    assert r.status_code == 201

    # The same MOBILE (the promoter's) is a duplicate, and the staff member gets the 3 choices.
    r = _new_lead(client, a, {"promoter": "Charan again", "mobile": "98754 35211"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DUPLICATE_OWN"
    assert r.json()["detail"]["choices"] == ["overwrite", "create_new", "cancel"]
