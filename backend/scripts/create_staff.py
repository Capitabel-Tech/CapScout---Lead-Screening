"""Create a staff login, or reset an existing one's password.

Usage (from backend/):
    uv run python scripts/create_staff.py EMP001 "Ravi Kumar"
    uv run python scripts/create_staff.py ADM001 "Admin" --role ADMIN
    uv run python scripts/create_staff.py EMP001 "Ravi Kumar" --reset-password

The password is typed at a hidden prompt (never on the command line).
"""

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password  # noqa: E402
from app.db import get_sessionmaker  # noqa: E402
from app.models import AuditLog, Staff, StaffRole  # noqa: E402

MIN_LENGTH = 8


def read_password() -> str:
    if not sys.stdin.isatty():  # piped input, e.g. for automated setup
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return first


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("employee_code")
    p.add_argument("full_name")
    p.add_argument("--role", choices=[r.value for r in StaffRole], default=StaffRole.FIELD_STAFF.value)
    p.add_argument("--reset-password", action="store_true", help="change the password of an existing login")
    args = p.parse_args()

    code = args.employee_code.strip().upper()
    password = read_password()
    if len(password) < MIN_LENGTH:
        print(f"Password must be at least {MIN_LENGTH} characters.", file=sys.stderr)
        return 1

    with get_sessionmaker()() as db:
        staff = db.scalar(select(Staff).where(Staff.employee_code == code))
        if staff and not args.reset_password:
            print(f"{code} already exists. Use --reset-password to change its password.", file=sys.stderr)
            return 1
        if staff is None and args.reset_password:
            print(f"{code} does not exist.", file=sys.stderr)
            return 1
        if staff is None:
            staff = Staff(
                employee_code=code,
                full_name=args.full_name.strip(),
                role=StaffRole(args.role),
                password_hash=hash_password(password),
            )
            db.add(staff)
            db.flush()
            action = "STAFF_CREATED"
        else:
            staff.password_hash = hash_password(password)
            action = "STAFF_PASSWORD_RESET"
        db.add(AuditLog(action=action, entity_type="staff", entity_id=str(staff.id), details={"code": code}))
        db.commit()
    print(f"{action.replace('_', ' ').capitalize()}: {code} ({args.full_name}, {args.role})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
