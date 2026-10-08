"""Copy fields_v1.json into field_definitions (idempotent)."""

from sqlalchemy import Connection, update
from sqlalchemy.dialects.postgresql import insert

from app.fields.catalog import load_catalog
from app.models import FieldDefinition


def sync_catalog(conn: Connection) -> int:
    cat = load_catalog()
    sections = {s["key"]: s for s in cat.sections}
    rows = [
        {
            "key": f.key,
            "label": f.label,
            "excel_column": f.excel_column,
            "position": f.position,
            "field_type": f.field_type,
            "options": list(f.options) if f.options else None,
            "unit": f.unit,
            "section_key": f.section,
            "section_label": sections[f.section]["label"],
            "section_order": sections[f.section]["display_order"],
            "display_order": f.display_order,
            "counts_toward_progress": f.counts_toward_progress,
            "system_source": f.system_source,
            "is_active": True,
        }
        for f in cat.fields
    ]
    stmt = insert(FieldDefinition).values(rows)
    # zoho_api_name is deliberately left alone: it is maintained separately.
    updatable = [c for c in rows[0] if c != "key"]
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"], set_={c: getattr(stmt.excluded, c) for c in updatable}
        )
    )
    # A field the client later removed stays in the table (old meetings may mention it) but is switched off.
    conn.execute(update(FieldDefinition).where(FieldDefinition.key.not_in([r["key"] for r in rows])).values(is_active=False))
    return len(rows)
