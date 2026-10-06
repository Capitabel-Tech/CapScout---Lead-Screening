"""The Convert-to-Lead form: Zoho's own Lead fields, pre-filled, validated, and sent as confirmed."""

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import ConversionStatus, Customer
from app.zoho import leadform
from tests.test_zoho_sync import FakeZoho, _customer, _setup_lead, run


def raw(api, label, dtype, req=False, options=None, custom=False, create=True, read_only=False):
    return {
        "api_name": api,
        "display_label": label,
        "data_type": dtype,
        "system_mandatory": req,
        "custom_field": custom,
        "view_type": {"create": create},
        "read_only": read_only,
        "length": 255 if dtype in ("text", "email", "phone") else None,
        "pick_list_values": [{"actual_value": o, "display_value": o} for o in (options or [])],
        "visible": True,
    }


RAW_FIELDS = [
    raw("Owner", "Lead Owner", "ownerlookup"),
    raw("Company", "Company", "text"),
    raw("Last_Name", "Last Name", "text", req=True),
    raw("Email", "Email", "email"),
    raw("Mobile", "Mobile", "phone"),
    raw("Industry", "Industry", "picklist", options=["-None-", "ERP", "Wireless Industry"]),
    raw("Annual_Revenue", "Annual Revenue", "currency"),
    raw("City", "Address - City", "text"),
    raw("Latitude", "Address - Latitude", "double"),
    raw("Description", "Description", "textarea"),
    raw("Loan_Type", "Loan Type", "picklist", options=["-None-", "LAP", "Business Loan", "Working Capital"], custom=True),
    raw("Loan_Required", "Loan Required (₹L)", "decimal", custom=True),
    raw("Purpose", "Purpose", "picklist", options=["Working Capital", "Expansion"], custom=True),
    raw("Created_Time", "Created Time", "datetime", create=False),
    raw("Hidden_Thing", "Read only", "text", read_only=True),
    raw("State", "Address - State", "picklist", options=[f"State {i}" for i in range(4000)]),
]
FIELDS = leadform.parse_fields(RAW_FIELDS)


@pytest.fixture(autouse=True)
def zoho_form(monkeypatch):
    async def fake_load(cfg, force=False):
        return FIELDS

    monkeypatch.setattr(leadform, "load_lead_fields", fake_load)
    monkeypatch.setattr(get_settings(), "zoho_mcp_url", "https://example.invalid/mcp/abcdefghijklmnopqrstuvwxyz/message")


def _form(client, headers, cid):
    r = client.get(f"/api/customers/{cid}/convert-form", headers=headers)
    assert r.status_code == 200, r.text
    return {f["api_name"]: f for f in r.json()["fields"]}


def test_form_shows_only_the_zoho_create_form_fields():
    apis = [f["api_name"] for f in FIELDS]
    assert "Owner" not in apis and "Latitude" not in apis  # not typed by hand
    assert "Created_Time" not in apis and "Hidden_Thing" not in apis  # not in the create form / read only
    loan = next(f for f in FIELDS if f["api_name"] == "Loan_Type")
    assert loan["options"] == ["LAP", "Business Loan", "Working Capital"]  # "-None-" is not a choice
    assert next(f for f in FIELDS if f["api_name"] == "Last_Name")["required"] is True
    state = next(f for f in FIELDS if f["api_name"] == "State")
    assert state["kind"] == "text" and state["options"] is None  # 4000 choices: typed, not listed


def test_form_is_prefilled_from_what_the_app_collected(client, make_staff):
    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a, loan_required="25", purpose="Working Capital", industry="Textiles")
    # The lead's address is never typed: the first meeting's GPS place gives it (set once, in the background).
    from app.db import get_sessionmaker
    from app.services.places import resolve_pending

    with get_sessionmaker()() as s:
        resolve_pending(s, get_settings(), lookup=lambda cfg, lat, lng: {"place": "Kukatpally, Hyderabad", "area": "Hyderabad"})
    form = _form(client, a, cid)

    assert form["Last_Name"]["value"] == "Ramesh Kumar" and form["Last_Name"]["prefilled_from"] == "Promoter"
    assert form["Company"]["value"] == "RK Traders"
    assert form["Mobile"]["value"] == "9876543210"
    assert form["City"]["value"] == "Hyderabad"
    # A Zoho field with the same label as one of our fields fills itself:
    assert form["Loan_Required"]["value"] == 25.0
    assert form["Purpose"]["value"] == "Working Capital"
    # ...but never with a value Zoho would reject: "Textiles" is not one of Zoho's Industry choices.
    assert form["Industry"]["value"] is None
    # Nothing to take from the app for these:
    assert form["Email"]["value"] is None and form["Loan_Type"]["value"] is None
    assert "Purpose: Working Capital" in form["Description"]["value"]


def test_confirmed_values_are_stored_and_sent_to_zoho_exactly(client, make_staff, db):
    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a)
    r = client.post(
        f"/api/customers/{cid}/convert",
        json={"lead_values": {
            "Last_Name": "Ramesh Kumar", "Company": "RK Traders (edited)", "Mobile": "9876543210",
            "Loan_Type": "LAP", "Annual_Revenue": "180.5", "Email": "", "Not_A_Zoho_Field": "ignored",
        }},
        headers=a,
    )
    assert r.status_code == 200 and r.json()["conversion_status"] == "CONVERTING"
    assert _customer(db, cid).zoho_lead_payload == {
        "Last_Name": "Ramesh Kumar", "Company": "RK Traders (edited)", "Mobile": "9876543210",
        "Loan_Type": "LAP", "Annual_Revenue": 180.5,
    }

    fake = FakeZoho()
    run(fake)  # the meeting goes first, then the Lead
    lead = next(iter(fake.leads.values()))
    assert lead == {  # exactly what was confirmed: no hidden extras, no ignored keys
        "Last_Name": "Ramesh Kumar", "Company": "RK Traders (edited)", "Mobile": "9876543210",
        "Loan_Type": "LAP", "Annual_Revenue": 180.5,
    }
    assert _customer(db, cid).conversion_status == ConversionStatus.CONVERTED


def test_invalid_form_is_refused_and_nothing_changes(client, make_staff, db):
    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a)
    r = client.post(
        f"/api/customers/{cid}/convert",
        json={"lead_values": {"Company": "X", "Loan_Type": "Mortgage", "Email": "not-an-email", "Annual_Revenue": "lots"}},
        headers=a,
    )
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert errors["Last_Name"] == "required"
    assert errors["Loan_Type"] == "choose one of the options"
    assert errors["Email"] == "enter a valid email address"
    assert errors["Annual_Revenue"] == "enter a valid number"
    c = _customer(db, cid)
    assert c.conversion_status == ConversionStatus.NOT_CONVERTED and c.zoho_lead_payload is None


def test_retry_after_failure_keeps_the_confirmed_values(client, make_staff, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "zoho_max_attempts", 1)
    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a)
    client.post(f"/api/customers/{cid}/convert", json={"lead_values": {"Last_Name": "Ramesh", "Loan_Type": "LAP"}}, headers=a)
    fake = FakeZoho()
    fake.fail_on = {("createRecords", "Leads")}
    run(fake)
    assert _customer(db, cid).conversion_status == ConversionStatus.CONVERSION_FAILED

    fake.fail_on = set()
    client.post(f"/api/customers/{cid}/convert", json={}, headers=a)  # "Retry conversion": no new form
    run(fake)
    assert next(iter(fake.leads.values())) == {"Last_Name": "Ramesh", "Loan_Type": "LAP"}


def test_convert_without_a_form_still_builds_a_default_lead(client, make_staff, db):
    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a)
    assert client.post(f"/api/customers/{cid}/convert", json={}, headers=a).status_code == 200
    fake = FakeZoho()
    run(fake)
    lead = next(iter(fake.leads.values()))
    assert lead["Last_Name"] == "Ramesh Kumar" and lead["Company"] == "RK Traders"


def test_form_needs_zoho_and_the_right_staff(client, make_staff, monkeypatch):
    _, a = make_staff("A1")
    _, b = make_staff("B1")
    cid, _ = _setup_lead(client, a)
    assert client.get(f"/api/customers/{cid}/convert-form", headers=b).status_code == 404

    async def broken(cfg, force=False):
        raise RuntimeError("Zoho is down")

    monkeypatch.setattr(leadform, "load_lead_fields", broken)
    r = client.get(f"/api/customers/{cid}/convert-form", headers=a)
    assert r.status_code == 503 and "Zoho is down" in r.json()["detail"]
    r = client.post(f"/api/customers/{cid}/convert", json={"lead_values": {"Last_Name": "X"}}, headers=a)
    assert r.status_code == 503
    # a failed form load never starts a conversion
    assert client.get(f"/api/customers/{cid}", headers=a).json()["conversion_status"] == "NOT_CONVERTED"


def test_a_later_meeting_never_overwrites_the_confirmed_form(client, make_staff, db):
    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a)
    client.post(
        f"/api/customers/{cid}/convert",
        json={"lead_values": {"Last_Name": "Ramesh Kumar", "Company": "RK Traders (edited)", "Description": "Edited by staff"}},
        headers=a,
    )
    fake = FakeZoho()
    run(fake)
    lead_id = next(iter(fake.leads))

    from tests.test_meetings import _meeting, _post

    # A meeting that changes nothing the Zoho Lead has a field for.
    _post(client, a, cid, _meeting({"urgency": "Immediate"}, started="2026-09-03T10:00:00+05:30"))
    run(fake)
    assert fake.calls_to("updateRecord", "Leads") == []  # nothing to update, so no call at all
    assert fake.leads[lead_id]["Company"] == "RK Traders (edited)"
    assert fake.leads[lead_id]["Description"] == "Edited by staff"


def test_the_description_block_stays_current_after_later_meetings(client, make_staff, db):
    from tests.test_meetings import _meeting, _post

    _, a = make_staff("A1")
    cid, _ = _setup_lead(client, a, loan_required="50")
    form = _form(client, a, cid)  # the Description arrives pre-filled with the app's block
    client.post(
        f"/api/customers/{cid}/convert",
        json={"lead_values": {"Last_Name": "Ramesh", "Description": "My call note.\n\n" + form["Description"]["value"]}},
        headers=a,
    )
    fake = FakeZoho()
    run(fake)
    lead_id = next(iter(fake.leads))
    assert "Loan Required (₹L): 50" in fake.leads[lead_id]["Description"]

    # Meeting 2: the loan goes 50 -> 60. Zoho has no box for it yet, but the Description must follow.
    _post(client, a, cid, _meeting({"loan_required": "60"}, started="2026-09-03T10:00:00+05:30"))
    run(fake)
    description = fake.leads[lead_id]["Description"]
    assert description.startswith("My call note.")
    assert "Loan Required (₹L): 60" in description and "Loan Required (₹L): 50" not in description
