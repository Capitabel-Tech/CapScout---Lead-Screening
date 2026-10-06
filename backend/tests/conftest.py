"""Test setup: a real Postgres database whose name must end in `_test`.

Set TEST_DATABASE_URL (environment or backend/.env). The schema is rebuilt
from the Alembic migrations once per run and data is truncated between tests.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import jwt
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, make_url, text

BACKEND = Path(__file__).resolve().parents[1]
TEST_SECRET = "test-secret-at-least-32-characters-long!!"

_url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(BACKEND / ".env").get("TEST_DATABASE_URL")
if not _url:
    pytest.exit("Set TEST_DATABASE_URL (a database whose name ends in _test)", returncode=2)
if not (make_url(_url).database or "").endswith("_test"):
    pytest.exit("Refusing to run: TEST_DATABASE_URL database name must end in _test", returncode=2)

os.environ["DATABASE_URL"] = _url
os.environ["JWT_SECRET"] = TEST_SECRET
os.environ["ZOHO_MCP_URL"] = ""  # tests never talk to the real Zoho
os.environ["ZOHO_SYNC_ENABLED"] = "false"
os.environ["GEOCODING_ENABLED"] = "false"  # tests never call a real map service
os.environ["DEV_AUTO_LOGIN"] = ""  # never skip sign-in in tests unless a test enables it

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_sessionmaker  # noqa: E402
from app.main import create_app  # noqa: E402
from app.auth import SESSION_COOKIE, hash_password  # noqa: E402
from app.models import Staff, StaffRole  # noqa: E402

get_settings.cache_clear()

DATA_TABLES = ["audit_log", "meetings", "customers", "staff"]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    engine = create_engine(_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    engine.dispose()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _clean():
    from app.zoho import leadform

    leadform._cache.update(at=0.0, fields=None)  # Zoho form metadata is cached: start every test fresh
    from app.services import places

    places._cache.clear()
    yield
    with get_sessionmaker()() as db:
        db.execute(text(f"TRUNCATE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE"))
        db.commit()


@pytest.fixture
def db():
    with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def client():
    return TestClient(create_app())


TEST_PASSWORD = "correct-horse-battery"
_TEST_HASH = hash_password(TEST_PASSWORD)  # hashed once; argon2 is deliberately slow


def make_token(staff_id: uuid.UUID, *, secret: str = TEST_SECRET, exp_in: int = 3600) -> str:
    return jwt.encode({"sub": str(staff_id), "exp": int(time.time()) + exp_in}, secret, algorithm="HS256")


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


@pytest.fixture
def make_staff(db):
    def _make(code: str, role: StaffRole = StaffRole.FIELD_STAFF, active: bool = True):
        staff = Staff(
            employee_code=code, full_name=f"Staff {code}", role=role, is_active=active, password_hash=_TEST_HASH
        )
        db.add(staff)
        db.commit()
        return staff, session_headers(make_token(staff.id))

    return _make
