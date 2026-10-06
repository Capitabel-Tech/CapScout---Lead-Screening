from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import func, select

from app.fields.catalog import FieldValueError, clean_value, load_catalog, normalize_mobile
from app.models import FieldDefinition

EXCEL = Path(__file__).resolve().parents[2] / "Capitabel_MSME_Lead_Screening_Tracker.xlsx"


def test_catalog_matches_excel_headers_exactly():
    ws = openpyxl.load_workbook(EXCEL)["Lead Screening"]
    headers = [c.value for c in ws[1] if c.value is not None]
    cat = load_catalog()
    assert [f.label for f in cat.fields] == headers
    assert len(cat.fields) == 44
    assert cat.progress_total == 41


def test_every_field_is_in_a_section():
    cat = load_catalog()
    section_keys = {s["key"] for s in cat.sections}
    assert {f.section for f in cat.fields} <= section_keys


def test_catalog_seeded_into_database(db):
    assert db.scalar(select(func.count()).select_from(FieldDefinition)) == 44
    grade = db.get(FieldDefinition, "opportunity_grade")
    assert grade.options == ["A – Priority", "B – Develop", "C – Selective", "D – Reject"]


@pytest.mark.parametrize(
    "key,value,expected",
    [
        ("source_type", "DSA", "DSA"),
        ("loan_required", "25.50", "25.5"),
        ("loan_required", 40, "40"),
        ("next_action_date", "2026-10-15", "2026-10-15"),
        ("mobile", "+91 98765 43210", "9876543210"),
        ("status", "  Follow up next week ", "Follow up next week"),
        ("litigation_dispute", "None", "None"),
        ("promoter", "", None),
    ],
)
def test_clean_value_accepts(key, value, expected):
    assert clean_value(key, value) == expected


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_type", "Walk-in"),  # not an Excel option
        ("loan_required", "-5"),
        ("loan_required", "lots"),
        ("next_action_date", "15/10/2026"),
        ("mobile", "12345"),
        ("lead_id", "X"),  # system field
        ("made_up_field", "x"),
    ],
)
def test_clean_value_rejects(key, value):
    with pytest.raises(FieldValueError):
        clean_value(key, value)


def test_normalize_mobile():
    assert normalize_mobile("09876543210") == "9876543210"
    assert normalize_mobile("919876543210") == "9876543210"
    assert normalize_mobile("98765") is None
