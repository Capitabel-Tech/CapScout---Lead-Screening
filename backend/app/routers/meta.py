from fastapi import APIRouter

from app.auth import CurrentStaff
from app.fields.catalog import load_catalog
from app.models import Staff

router = APIRouter(tags=["meta"])


def staff_out(staff: Staff) -> dict:
    return {
        "id": str(staff.id),
        "employee_code": staff.employee_code,
        "full_name": staff.full_name,
        "role": staff.role.value,
    }


@router.get("/me")
def me(staff: CurrentStaff) -> dict:
    return staff_out(staff)


@router.get("/fields")
def fields(_: CurrentStaff) -> dict:
    """The 44-field catalogue the phone renders its forms from."""
    cat = load_catalog()
    return {
        "version": cat.version,
        "progress_total": cat.progress_total,
        "sections": list(cat.sections),
        "fields": [
            {
                "key": f.key,
                "label": f.label,
                "field_type": f.field_type,
                "options": list(f.options) if f.options else None,
                "unit": f.unit,
                "section": f.section,
                "display_order": f.display_order,
                "counts_toward_progress": f.counts_toward_progress,
                "system_source": f.system_source,
            }
            for f in cat.fields
        ],
    }
