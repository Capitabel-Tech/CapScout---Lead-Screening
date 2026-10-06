"""Staff-level data isolation. Every customer query goes through here.

Field staff see only customers they own. Admins see everything. Supervisor
team views are a future improvement, so supervisors are treated like field
staff until teams exist.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Customer, Staff, StaffRole


def scope_customers(stmt: Select, staff: Staff) -> Select:
    if staff.role == StaffRole.ADMIN:
        return stmt
    return stmt.where(Customer.owner_staff_id == staff.id)


def get_visible_customer(db: Session, staff: Staff, customer_id: uuid.UUID) -> Customer:
    """Return the customer or 404. Never reveals that another staff member's record exists."""
    customer = db.scalar(scope_customers(select(Customer).where(Customer.id == customer_id), staff))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return customer
