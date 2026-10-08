from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import func, select

from app.fields.catalog import FieldValueError, clean_value, load_catalog, normalize_mobile, progress_keys_for
from app.models import FieldDefinition

EXCEL = Path(__file__).resolve().parents[2] / "Capitabel_MSME_Lead_Screening_Tracker.xlsx"


def test_catalog_is_the_excel_plus_the_clients_changes():
    ws = openpyxl.load_workbook(EXCEL)["Lead Screening"]
    headers = [c.value for c in ws[1] if c.value is not None]
    cat = load_catalog()
    labels = {f.label for f in cat.fields}
    # Every Excel field is still there, except what the client changed or removed.
    renamed = {
        "Promoter": "POC (Point of Contact)",
        "Loan Required (₹L)": "Loan Required (₹)",
        "Annual Turnover (₹L)": "Average Monthly Turnover (₹)",
        "Monthly Banking (₹L)": "Monthly Banking (₹)",
        "Existing Debt (₹L)": "Existing Debt (₹)",
        "Monthly EMI (₹L)": "Monthly EMI (₹)",
    }
    for h in headers:
        if h not in ("Monthly Surplus (₹L)", "Property Value (₹L)", "Existing Mortgage"):
            assert renamed.get(h, h) in labels, h
    assert not labels & {"Monthly Surplus (₹L)", "Property Value (₹L)", "Existing Mortgage"}
    assert len(cat.fields) == 48  # 43 from the Excel - 2 removed + 7 new
    assert cat.progress_total == 40
    by = cat.by_key
    assert by["constitution"].options == ("Proprietorship", "Partnership", "LLP", "Pvt Ltd", "Other")
    assert by["purpose"].options == ("Working Capital", "Expansion", "Capex", "Other")
    assert by["property_type"].options == ("Residential", "Commercial", "Industrial", "Land", "Other")
    assert by["property_documents"].options == ("Yes", "No", "Unknown")
    assert "property_value" not in by and "existing_mortgage" not in by
    assert "monthly_surplus" not in by


def test_every_dropdown_with_other_has_a_box_to_type_it():
    cat = load_catalog()
    for f in cat.fields:
        if f.options and "Other" in f.options:
            box = cat.by_key[f"{f.key}_other"]
            assert box.field_type == "text" and not box.counts_toward_progress and box.section == f.section


def test_credit_flags_are_in_the_money_step_and_property_order():
    cat = load_catalog()
    section = {f.key: f.section for f in cat.fields}
    for key in ("overdue", "bounces", "settlement_write_off", "litigation_dispute"):
        assert section[key] == "money"
    property_step = [f.key for f in sorted(cat.fields, key=lambda f: f.display_order) if f.section == "property"]
    assert property_step == [
        "property_available", "property_type", "property_type_other",
        "property_documents",
    ]


def test_direct_source_hides_source_name_and_contact_from_progress():
    assert {"source_name", "source_contact"} <= progress_keys_for({"source_type": "DSA"})
    direct = progress_keys_for({"source_type": "Direct"})
    assert not {"source_name", "source_contact"} & direct and len(direct) == 38
    no_property = progress_keys_for({"property_available": "No"})
    assert not {"property_type", "property_documents"} & no_property and len(no_property) == 38
    unsecured = progress_keys_for({"secured_unsecured": "Unsecured"})
    assert not {"property_available", "property_type", "property_documents"} & unsecured and len(unsecured) == 37
    assert len(progress_keys_for({"secured_unsecured": "Open to both"})) == 40
    assert len(progress_keys_for({"source_type": "Direct", "secured_unsecured": "Unsecured"})) == 35


def test_every_field_is_in_a_section():
    cat = load_catalog()
    section_keys = {s["key"] for s in cat.sections}
    assert {f.section for f in cat.fields} <= section_keys


def test_catalog_seeded_into_database(db):
    assert db.scalar(select(func.count()).select_from(FieldDefinition)) == 48
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
