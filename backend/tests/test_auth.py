import uuid

from sqlalchemy import func, select

from app.auth import SESSION_COOKIE
from app.models import AuditLog
from tests.conftest import TEST_PASSWORD, make_token, session_headers


def _login(client, code, password=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"employee_code": code, "password": password})


def test_login_sets_httponly_cookie_and_me_works(client, make_staff):
    make_staff("EMP001")
    r = _login(client, "emp001")  # code is case-insensitive
    assert r.status_code == 200
    assert r.json()["employee_code"] == "EMP001"
    cookie = r.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()
    assert "Path=/api" in cookie
    # TestClient keeps the cookie for later requests.
    assert client.get("/api/me").json()["employee_code"] == "EMP001"


def test_wrong_password_and_unknown_code_look_the_same(client, make_staff):
    make_staff("EMP001")
    a = _login(client, "EMP001", "wrong-password")
    b = _login(client, "NOBODY", "wrong-password")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_inactive_staff_cannot_log_in(client, make_staff):
    make_staff("EMP009", active=False)
    assert _login(client, "EMP009").status_code == 401


def test_lockout_after_five_failures(client, make_staff, db):
    make_staff("EMP001")
    for _ in range(5):
        assert _login(client, "EMP001", "nope").status_code == 401
    # Even the right password is refused while locked.
    assert _login(client, "EMP001").status_code == 429
    failures = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "LOGIN_FAILED"))
    assert failures == 5


def test_logout_clears_cookie(client, make_staff):
    make_staff("EMP001")
    _login(client, "EMP001")
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    assert client.get("/api/me").status_code == 401


def test_requires_session(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/customers").status_code == 401


def test_rejects_forged_or_expired_or_unknown_sessions(client, make_staff):
    staff, _ = make_staff("A1")
    forged = make_token(staff.id, secret="some-other-secret-some-other-secret-1234")
    expired = make_token(staff.id, exp_in=-10)
    unknown = make_token(uuid.uuid4())
    for token in (forged, expired, unknown, "garbage"):
        assert client.get("/api/me", headers=session_headers(token)).status_code == 401


def test_deactivated_staff_lose_access_immediately(client, make_staff, db):
    staff, headers = make_staff("A1")
    assert client.get("/api/me", headers=headers).status_code == 200
    staff.is_active = False
    db.commit()
    assert client.get("/api/me", headers=headers).status_code == 401


# --- DEV_AUTO_LOGIN (testing-only switch) -------------------------------------


def test_dev_auto_login_skips_sign_in(client, make_staff, monkeypatch):
    from app.config import get_settings

    make_staff("DEV001")
    monkeypatch.setattr(get_settings(), "dev_auto_login", "dev001")
    r = client.get("/api/me")
    assert r.status_code == 200 and r.json()["employee_code"] == "DEV001"


def test_dev_auto_login_ignores_inactive_staff(client, make_staff, monkeypatch):
    from app.config import get_settings

    make_staff("DEV001", active=False)
    monkeypatch.setattr(get_settings(), "dev_auto_login", "DEV001")
    assert client.get("/api/me").status_code == 401


def test_dev_auto_login_refused_in_production():
    import pytest
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://x/y", jwt_secret="s", cookie_secure=True, dev_auto_login="DEV001")
