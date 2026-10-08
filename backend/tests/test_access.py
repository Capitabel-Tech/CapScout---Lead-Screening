from sqlalchemy import select

from app.models import AuditLog, StaffRole


def _create(client, headers, **values):
    return client.post("/api/customers", json={"values": values}, headers=headers)


# --- staff isolation (Test 6) -------------------------------------------------


def test_staff_only_see_their_own_customers(client, make_staff):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    ra = _create(client, a, promoter="Ramesh Kumar", business_name="RK Traders")
    rb = _create(client, b, promoter="Suresh", business_name="SS Foods")
    assert ra.status_code == rb.status_code == 201

    a_list = client.get("/api/customers", headers=a).json()
    assert [i["promoter"] for i in a_list["items"]] == ["Ramesh Kumar"]

    b_id = rb.json()["id"]
    assert client.get(f"/api/customers/{b_id}", headers=a).status_code == 404
    assert client.get(f"/api/customers/{b_id}", headers=b).status_code == 200


def test_search_is_also_scoped(client, make_staff):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    _create(client, b, promoter="Ramesh Other")
    assert client.get("/api/customers?q=ramesh", headers=a).json()["total"] == 0


def test_admin_sees_all(client, make_staff):
    _, a = make_staff("A1")
    _, admin = make_staff("ADM", role=StaffRole.ADMIN)
    _create(client, a, promoter="Ramesh")
    assert client.get("/api/customers", headers=admin).json()["total"] == 1


# --- creation, progress, tabs -----------------------------------------------


def test_create_prospect_progress_and_tab(client, make_staff):
    _, a = make_staff("A1")
    r = _create(client, a, promoter="Ramesh", business_name="RK", mobile="9876543210", source_type="DSA")
    body = r.json()
    assert body["conversion_status"] == "NOT_CONVERTED"
    assert body["progress"] == {"filled": 4, "total": 40, "percent": 10}
    assert body["lead_ref"] == "MSME-0001"
    sections = {s["key"]: s for s in body["sections"]}
    assert sections["lead"]["total"] == 7  # 10 fields minus Lead ID, Date, SM Name
    assert sections["lead"]["filled"] == 4

    assert client.get("/api/customers?tab=not_converted", headers=a).json()["total"] == 1
    assert client.get("/api/customers?tab=converted", headers=a).json()["total"] == 0


def test_create_requires_identity_and_valid_values(client, make_staff):
    _, a = make_staff("A1")
    assert _create(client, a, source_type="DSA").status_code == 422
    r = _create(client, a, promoter="X", purpose="Holiday")
    assert r.status_code == 422
    assert "purpose" in r.json()["detail"]["errors"]


# --- duplicate mobile rule --------------------------------------------------


def test_duplicate_mobile_other_staff_is_blocked(client, make_staff, db):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    _create(client, a, promoter="Ramesh", mobile="9876543210")

    r = _create(client, b, promoter="Ramesh K", mobile="+91 98765-43210")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail == {
        "code": "ASSIGNED_TO_OTHER_STAFF",
        "message": "This customer is already assigned to another staff member.",
    }
    # Even with "create_new", another staff member's customer cannot be duplicated.
    r = client.post(
        "/api/customers",
        json={"values": {"promoter": "R", "mobile": "9876543210"}, "on_duplicate": "create_new"},
        headers=b,
    )
    assert r.status_code == 409
    assert client.get("/api/customers", headers=b).json()["total"] == 0
    assert db.scalar(select(AuditLog).where(AuditLog.action == "DUPLICATE_BLOCKED")) is not None


def test_duplicate_mobile_own_record_offers_choices(client, make_staff):
    _, a = make_staff("A1")
    first = _create(client, a, promoter="Ramesh", mobile="9876543210", purpose="Expansion").json()

    r = _create(client, a, promoter="Ramesh Kumar", mobile="9876543210")
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "DUPLICATE_OWN"
    assert d["choices"] == ["overwrite", "create_new", "cancel"]
    assert d["matches"][0]["id"] == first["id"]
    assert d["matches"][0]["purpose"] == "Expansion"
    assert client.get("/api/customers", headers=a).json()["total"] == 1


def test_duplicate_mobile_own_create_new(client, make_staff):
    _, a = make_staff("A1")
    _create(client, a, promoter="Ramesh", mobile="9876543210")
    r = client.post(
        "/api/customers",
        json={"values": {"promoter": "Ramesh 2", "mobile": "9876543210"}, "on_duplicate": "create_new"},
        headers=a,
    )
    assert r.status_code == 201
    assert client.get("/api/customers", headers=a).json()["total"] == 2


def test_duplicate_mobile_own_overwrite(client, make_staff, db):
    _, a = make_staff("A1")
    first = _create(client, a, promoter="Ramesh", mobile="9876543210", purpose="Expansion").json()
    r = client.post(
        "/api/customers",
        json={
            "values": {"promoter": "Ramesh Kumar", "mobile": "9876543210", "urgency": "Immediate"},
            "on_duplicate": "overwrite",
            "overwrite_customer_id": first["id"],
        },
        headers=a,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == first["id"]
    assert body["values"]["promoter"] == "Ramesh Kumar"
    assert body["values"]["purpose"] == "Expansion"  # untouched fields stay
    assert body["values"]["urgency"] == "Immediate"
    assert client.get("/api/customers", headers=a).json()["total"] == 1

    log = db.scalar(select(AuditLog).where(AuditLog.action == "PROSPECT_OVERWRITTEN"))
    assert {"field": "promoter", "old": "Ramesh", "new": "Ramesh Kumar", "type": "UPDATED"} in log.details["changes"]


def test_overwrite_cannot_target_someone_elses_record(client, make_staff):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    mine = _create(client, a, promoter="Mine", mobile="9000000001").json()
    theirs = _create(client, b, promoter="Theirs", mobile="9000000002").json()
    r = client.post(
        "/api/customers",
        json={
            "values": {"promoter": "Hijack", "mobile": "9000000001"},
            "on_duplicate": "overwrite",
            "overwrite_customer_id": theirs["id"],
        },
        headers=a,
    )
    assert r.status_code == 422
    assert client.get(f"/api/customers/{mine['id']}", headers=a).json()["values"]["promoter"] == "Mine"
