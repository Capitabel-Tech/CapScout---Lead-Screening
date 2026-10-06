"""Readable place for each meeting, worked out from its GPS in the background."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Meeting
from app.services.places import build_place_name, resolve_pending
from tests.test_meetings import GPS_A, _meeting, _new_lead, _post
from tests.test_zoho_sync import FakeZoho, _meeting_row, run


def _lead(client, headers, **kw):
    r = _new_lead(client, headers, {"promoter": "Ramesh Kumar", "business_name": "RK Traders", "mobile": "9876543210", **kw})
    assert r.status_code == 201, r.text
    return r.json()["customer_id"], r.json()["meeting"]["id"]


def _resolve(lookup, **kw):
    with get_sessionmaker()() as db:
        return resolve_pending(db, get_settings(), lookup=lookup, **kw)


def test_real_indian_map_data_gives_the_locality_not_a_ward_number():
    """What the map service really returns for a point in Anna Nagar, Chennai."""
    from app.services.places import build_area_name, build_place_name

    real = {"address": {"road": "2nd Avenue, Anna Nagar West", "neighbourhood": "Ward 99", "suburb": "Zone 8 Anna Nagar",
                        "town": "Maduravoyal", "city": "Chennai", "state": "Tamil Nadu", "country": "India"}}
    assert build_area_name(real) == "Anna Nagar West, Chennai"
    assert build_place_name(real) == "2nd Avenue, Anna Nagar West, Chennai, Tamil Nadu"
    # with no locality in the road, a zone name is cleaned ("Zone 8 Anna Nagar" -> "Anna Nagar")
    zone = {"address": {"road": "Main Road", "suburb": "Zone 8 Anna Nagar", "city": "Chennai"}}
    assert build_area_name(zone) == "Anna Nagar, Chennai"
    # a bare ward number is never used
    assert build_area_name({"address": {"neighbourhood": "Ward 99", "city": "Chennai"}}) == "Chennai"


def test_place_name_is_short_and_readable():
    data = {"address": {"road": "3rd Street", "neighbourhood": "Shanthi Colony", "suburb": "Anna Nagar",
                        "city": "Chennai", "state": "Tamil Nadu", "country": "India", "postcode": "600040"}}
    assert build_place_name(data) == "3rd Street, Shanthi Colony, Chennai, Tamil Nadu"
    # repeated names are not shown twice; missing parts are skipped
    assert build_place_name({"address": {"suburb": "Kukatpally", "city": "Kukatpally", "state": "Telangana"}}) == "Kukatpally, Telangana"
    assert build_place_name({"display_name": "Somewhere, India"}) == "Somewhere, India"
    assert build_place_name({}) is None


def test_place_is_worked_out_from_gps_and_shown_in_the_app(client, make_staff, db):
    _, a = make_staff("A1")
    cid, mid = _lead(client, a)
    seen = []

    def lookup(cfg, lat, lng):
        seen.append((lat, lng))
        return "Shanthi Colony, Anna Nagar, Chennai"

    assert _resolve(lookup) == 1
    assert seen == [(GPS_A["latitude"], GPS_A["longitude"])]  # only the numbers go to the map service
    assert _meeting_row(db, mid).start_place == "Shanthi Colony, Anna Nagar, Chennai"
    history = client.get(f"/api/customers/{cid}/meetings", headers=a).json()["items"]
    assert history[0]["place"] == "Shanthi Colony, Anna Nagar, Chennai"
    assert _resolve(lookup) == 0  # already done: not asked again


def test_each_meeting_keeps_its_own_place_and_the_lead_address_is_the_first_one(client, make_staff, db):
    _, a = make_staff("A1")
    cid, m1 = _lead(client, a)
    r = _post(client, a, cid, _meeting({}, gps={**GPS_A, "latitude": 17.50, "longitude": 78.35}, started="2026-09-03T10:00:00+05:30"))
    m2 = r.json()["id"]
    answers = iter([
        {"place": "2nd Street, Kukatpally, Hyderabad", "area": "Kukatpally, Hyderabad"},
        {"place": "Miyapur, Hyderabad", "area": "Miyapur, Hyderabad"},
    ])
    _resolve(lambda cfg, lat, lng: next(answers))
    assert _meeting_row(db, m1).start_place == "2nd Street, Kukatpally, Hyderabad"
    assert _meeting_row(db, m2).start_place == "Miyapur, Hyderabad"  # each meeting: its own place
    # the lead's address is the FIRST meeting's, and the second meeting did not change it
    assert client.get(f"/api/customers/{cid}", headers=a).json()["values"]["location"] == "Kukatpally, Hyderabad"


def test_location_is_never_typed_by_staff(client, make_staff, db):
    _, a = make_staff("A1")
    r = _new_lead(client, a, {"promoter": "X", "business_name": "Y", "location": "Typed by hand"})
    assert r.status_code == 201
    cid = r.json()["customer_id"]
    assert "location" not in client.get(f"/api/customers/{cid}", headers=a).json()["values"]  # ignored
    r = _post(client, a, cid, _meeting({"location": "Typed later", "purpose": "LAP"}, started="2026-09-03T10:00:00+05:30"))
    assert r.status_code == 201 and [c["field"] for c in r.json()["changes"]] == ["purpose"]  # only the real change
    assert "location" not in client.get(f"/api/customers/{cid}", headers=a).json()["values"]


def test_first_meeting_without_gps_leaves_the_address_for_the_first_one_that_has_it(client, make_staff, db):
    _, a = make_staff("A1")
    body = {"meeting": _meeting({"promoter": "X"}, gps=None, reason="Permission denied")}
    cid = client.post("/api/leads/new", json=body, headers=a).json()["customer_id"]
    _resolve(lambda cfg, lat, lng: {"place": "should not be used", "area": "nope"})  # nothing to look up
    assert "location" not in client.get(f"/api/customers/{cid}", headers=a).json()["values"]

    r = _post(client, a, cid, _meeting({}, started="2026-09-03T10:00:00+05:30"))  # a meeting WITH gps
    _resolve(lambda cfg, lat, lng: {"place": "Miyapur, Hyderabad", "area": "Miyapur, Hyderabad"})
    assert client.get(f"/api/customers/{cid}", headers=a).json()["values"]["location"] == "Miyapur, Hyderabad"
    # ...and from then on it is fixed
    _post(client, a, cid, _meeting({}, started="2026-09-04T10:00:00+05:30"))
    _resolve(lambda cfg, lat, lng: {"place": "Somewhere else", "area": "Somewhere else"})
    assert client.get(f"/api/customers/{cid}", headers=a).json()["values"]["location"] == "Miyapur, Hyderabad"


def test_the_address_set_from_gps_counts_toward_progress_and_is_in_the_first_meetings_history(client, make_staff, db):
    _, a = make_staff("A1")
    cid, m1 = _lead(client, a)
    before = client.get(f"/api/customers/{cid}", headers=a).json()["progress"]["filled"]
    _resolve(lambda cfg, lat, lng: {"place": "Kukatpally, Hyderabad", "area": "Kukatpally, Hyderabad"})
    assert client.get(f"/api/customers/{cid}", headers=a).json()["progress"]["filled"] == before + 1
    history = client.get(f"/api/customers/{cid}/meetings", headers=a).json()["items"][0]
    assert {"field": "location", "old": None, "new": "Kukatpally, Hyderabad", "type": "NEW"} in history["changes"]


def test_a_failing_map_service_never_affects_the_meeting_and_stops_after_three_tries(client, make_staff, db):
    _, a = make_staff("A1")
    cid, mid = _lead(client, a)

    def broken(cfg, lat, lng):
        raise RuntimeError("map service is down")

    for _ in range(5):
        _resolve(broken)
    m = _meeting_row(db, mid)
    assert m.start_place is None and m.place_attempts == 3  # gave up after 3, no endless retrying
    assert client.get(f"/api/customers/{cid}/meetings", headers=a).json()["items"][0]["gps_start"]["latitude"] == GPS_A["latitude"]

    # "no result" (e.g. the middle of the sea) counts as an attempt too
    cid2, mid2 = _lead(client, a, mobile="9876543299")
    _resolve(lambda cfg, lat, lng: None)
    assert _meeting_row(db, mid2).place_attempts == 1


def test_meetings_without_gps_are_ignored(client, make_staff):
    _, a = make_staff("A1")
    body = {"meeting": _meeting({"promoter": "X"}, gps=None, reason="Permission denied")}
    assert client.post("/api/leads/new", json=body, headers=a).status_code == 201
    called = []
    assert _resolve(lambda cfg, lat, lng: called.append(1)) == 0 and not called


def test_the_place_goes_to_zoho_as_the_meetings_location(client, make_staff, db):
    _, a = make_staff("A1")
    _, mid = _lead(client, a)
    _resolve(lambda cfg, lat, lng: "Shanthi Colony, Anna Nagar, Chennai")
    fake = FakeZoho()
    run(fake)
    event = next(iter(fake.events.values()))
    assert event["Venue"] == "Shanthi Colony, Anna Nagar, Chennai"
    assert "Place: Shanthi Colony, Anna Nagar, Chennai" in event["Description"]


def test_a_meeting_without_a_place_still_syncs_to_zoho(client, make_staff, db):
    _, a = make_staff("A1")
    _, mid = _lead(client, a)
    fake = FakeZoho()
    run(fake)  # no place was ever worked out
    event = next(iter(fake.events.values()))
    assert "Venue" not in event and "Place:" not in event["Description"]


# --- the Location box SHOWS the GPS place (GET /api/geo/reverse); nothing is saved from the browser ----

ANNA_NAGAR = {"address": {"road": "2nd Avenue", "suburb": "Anna Nagar West", "city_district": "Ward 99",
                          "city": "Chennai", "state": "Tamil Nadu", "country": "India"}}


def test_short_area_name():
    from app.services.places import build_area_name

    assert build_area_name(ANNA_NAGAR) == "Anna Nagar West, Chennai"
    assert build_area_name({"address": {"city": "Chennai"}}) == "Chennai"
    assert build_area_name({"address": {"suburb": "Kukatpally", "city": "Kukatpally"}}) == "Kukatpally"
    assert build_area_name({}) is None


def test_reverse_endpoint_returns_the_area_and_the_full_place(client, make_staff, monkeypatch):
    from app.services import places

    monkeypatch.setattr(get_settings(), "geocoding_enabled", True)
    calls = []
    monkeypatch.setattr(places, "nominatim_data", lambda cfg, lat, lng: calls.append((lat, lng)) or ANNA_NAGAR)
    _, a = make_staff("A1")

    r = client.get("/api/geo/reverse?lat=13.085&lng=80.2101", headers=a)
    assert r.status_code == 200
    assert r.json() == {"place": "2nd Avenue, Anna Nagar West, Chennai, Tamil Nadu", "area": "Anna Nagar West, Chennai"}
    assert calls == [(13.085, 80.2101)]  # only the two numbers were sent anywhere
    client.get("/api/geo/reverse?lat=13.08502&lng=80.21008", headers=a)  # a few metres away
    assert len(calls) == 1  # answered from the cache


def test_reverse_endpoint_never_fails_the_form(client, make_staff, monkeypatch):
    from app.services import places

    monkeypatch.setattr(get_settings(), "geocoding_enabled", True)
    _, a = make_staff("A1")

    def down(cfg, lat, lng):
        raise RuntimeError("map service is down")

    monkeypatch.setattr(places, "nominatim_data", down)
    assert client.get("/api/geo/reverse?lat=13.085&lng=80.2101", headers=a).json() == {"place": None, "area": None}
    monkeypatch.setattr(places, "nominatim_data", lambda cfg, lat, lng: None)  # e.g. the middle of the sea
    assert client.get("/api/geo/reverse?lat=0&lng=0", headers=a).json() == {"place": None, "area": None}
    monkeypatch.setattr(get_settings(), "geocoding_enabled", False)
    assert client.get("/api/geo/reverse?lat=13&lng=80", headers=a).json() == {"place": None, "area": None}


def test_reverse_endpoint_needs_sign_in_and_valid_numbers(client, make_staff):
    assert client.get("/api/geo/reverse?lat=13&lng=80").status_code == 401
    _, a = make_staff("A1")
    assert client.get("/api/geo/reverse?lat=999&lng=80", headers=a).status_code == 422
    assert client.get("/api/geo/reverse?lat=13", headers=a).status_code == 422
