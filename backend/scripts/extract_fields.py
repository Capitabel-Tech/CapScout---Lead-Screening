"""Generate app/fields/fields_v1.json from the client's Excel tracker.

The Excel file is the source of truth for field labels and dropdown options.
This script adds only what the Excel cannot express: a stable key, an input
type, and the mobile section each field belongs to. It fails loudly if the
Excel headers ever stop matching that mapping, so nothing is silently renamed.

Usage (from backend/):  uv run python scripts/extract_fields.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.cell_range import CellRange

ROOT = Path(__file__).resolve().parents[2]
EXCEL_PATH = ROOT / "Capitabel_MSME_Lead_Screening_Tracker.xlsx"
OUT_PATH = Path(__file__).resolve().parents[1] / "app" / "fields" / "fields_v1.json"

# Mobile steps, in display order, as in the client's UI prototype
# (MSME_Lead_Screening_Prototype.html): Lead, Business, Money, Property, Assess, Decide.
SECTIONS = [
    ("lead", "Lead & source"),
    ("business", "Business & loan need"),
    ("money", "Financials, documents & credit flags"),
    ("property", "Property details"),
    ("assess", "Screening assessment"),
    ("decide", "Recommendation & next action"),
]

# exact Excel label -> (key, field_type, section, unit, system_source)
# field_type "system" = filled by the app, excluded from progress (41 of 44 count).
# Within a section, fields display in the order listed here.
FIELD_MAP: dict[str, tuple[str, str, str, str | None, str | None]] = {
    "Lead ID": ("lead_id", "system", "lead", None, "application_ref"),
    "Date": ("date", "system", "lead", None, "meeting_date"),
    "SM Name": ("sm_name", "system", "lead", None, "staff_name"),
    "Source Type": ("source_type", "single_select", "lead", None, None),
    "Source Name": ("source_name", "text", "lead", None, None),
    "Source Contact": ("source_contact", "text", "lead", None, None),
    "Business Name": ("business_name", "text", "lead", None, None),
    "Promoter": ("promoter", "text", "lead", None, None),
    "Mobile": ("mobile", "phone", "lead", None, None),
    "Location": ("location", "text", "lead", None, None),
    "Constitution": ("constitution", "single_select", "business", None, None),
    "Industry": ("industry", "text", "business", None, None),
    "Vintage (Years)": ("vintage_years", "number", "business", "Years", None),
    "Loan Required (₹L)": ("loan_required", "number", "business", "₹L", None),
    "Purpose": ("purpose", "single_select", "business", None, None),
    "Urgency": ("urgency", "single_select", "business", None, None),
    "Secured/Unsecured": ("secured_unsecured", "single_select", "business", None, None),
    "Annual Turnover (₹L)": ("annual_turnover", "number", "money", "₹L", None),
    "Monthly Banking (₹L)": ("monthly_banking", "number", "money", "₹L", None),
    "Monthly Surplus (₹L)": ("monthly_surplus", "number", "money", "₹L", None),
    "Existing Debt (₹L)": ("existing_debt", "number", "money", "₹L", None),
    "Monthly EMI (₹L)": ("monthly_emi", "number", "money", "₹L", None),
    "GST Available": ("gst_available", "single_select", "money", None, None),
    "ITR/Financials": ("itr_financials", "single_select", "money", None, None),
    "Bank Statements": ("bank_statements", "single_select", "money", None, None),
    "Documents Readiness": ("documents_readiness", "single_select", "assess", None, None),
    "Property Available": ("property_available", "single_select", "property", None, None),
    "Property Value (₹L)": ("property_value", "number", "property", "₹L", None),
    "Existing Mortgage": ("existing_mortgage", "single_select", "property", None, None),
    "Overdue": ("overdue", "single_select", "property", None, None),
    "Bounces": ("bounces", "single_select", "property", None, None),
    "Settlement/Write-off": ("settlement_write_off", "single_select", "property", None, None),
    # No dropdown in the Excel; kept as free text per client decision.
    "Litigation/Dispute": ("litigation_dispute", "text", "property", None, None),
    "Business Quality": ("business_quality", "single_select", "assess", None, None),
    "Banking Quality": ("banking_quality", "single_select", "assess", None, None),
    "Credit Risk": ("credit_risk", "single_select", "assess", None, None),
    "Opportunity Grade": ("opportunity_grade", "single_select", "assess", None, None),
    "Likely Product": ("likely_product", "single_select", "assess", None, None),
    "Potential Lender": ("potential_lender", "text", "assess", None, None),
    "SM Recommendation": ("sm_recommendation", "single_select", "decide", None, None),
    # No dropdown in the Excel; kept as free text per client decision.
    "Status": ("status", "text", "decide", None, None),
    "Next Action": ("next_action", "single_select", "decide", None, None),
    "Next Action Date": ("next_action_date", "date", "decide", None, None),
    "Reason/Comments": ("reason_comments", "long_text", "decide", None, None),
}


# --- the client's own changes to the Excel list (decided 2026-10-08) -----------------------------
# Applied on top of the Excel so re-running this script never undoes them. Keys never change
# (stored values and Zoho mappings keep working); only labels, options and the list of fields do.
RELABEL = {
    "promoter": "POC (Point of Contact)",
    # Amounts are typed in full rupees (with commas), no longer in lakhs.
    "loan_required": "Loan Required (₹)",
    "annual_turnover": "Average Monthly Turnover (₹)",
    "monthly_banking": "Monthly Banking (₹)",
    "existing_debt": "Existing Debt (₹)",
    "monthly_emi": "Monthly EMI (₹)",
}
RUPEE_FIELDS = ["loan_required", "annual_turnover", "monthly_banking", "existing_debt", "monthly_emi"]
REMOVE_OPTIONS = {
    "constitution": ["Ltd"],
    "purpose": ["LAP", "Business Loan"],
}
ADD_OPTIONS = {"constitution": ["Other"]}
REMOVE_FIELDS = ["monthly_surplus", "property_value", "existing_mortgage"]
# The credit red flags move from the Property step to the Money step: Financials, red flags, then documents.
MOVE_TO_MONEY = ["overdue", "bounces", "settlement_write_off", "litigation_dispute"]


def _text_other(of: str, label: str, section: str) -> dict:
    """The "type it here" box shown when the dropdown `of` is set to "Other" (not counted in progress)."""
    return {
        "after": of,
        "field": {
            "key": f"{of}_other", "label": f"{label} (Other)", "field_type": "text", "options": None,
            "unit": None, "section": section, "counts_toward_progress": False, "system_source": None,
        },
    }


# Fixed positions for the new fields (they must stay the same forever: the database keeps them unique).
NEW_POSITIONS = {
    "constitution_other": 45,
    "source_type_other": 46,
    "purpose_other": 47,
    "likely_product_other": 48,
    "property_type": 49,
    "property_type_other": 50,
    "property_documents": 51,
}

# New fields, in the order they are added ("after" can be a field added just before it).
ADD_FIELDS = [
    _text_other("source_type", "Source Type", "lead"),
    _text_other("constitution", "Constitution", "business"),
    _text_other("purpose", "Purpose", "business"),
    _text_other("likely_product", "Likely Product", "assess"),
    {
        "after": "property_available",
        "field": {
            "key": "property_type", "label": "Property Type", "field_type": "single_select",
            "options": ["Residential", "Commercial", "Industrial", "Land", "Other"],
            "unit": None, "section": "property", "counts_toward_progress": True, "system_source": None,
        },
    },
    _text_other("property_type", "Property Type", "property"),
    {
        "after": "property_type_other",
        "field": {
            "key": "property_documents", "label": "Property Documents Available", "field_type": "single_select",
            "options": ["Yes", "No", "Unknown"],
            "unit": None, "section": "property", "counts_toward_progress": True, "system_source": None,
        },
    },
]


def apply_client_changes(fields: list[dict]) -> list[dict]:
    fields = [f for f in fields if f["key"] not in REMOVE_FIELDS]
    for f in fields:
        if f["key"] in RELABEL:
            f["label"] = RELABEL[f["key"]]
        if f["key"] in RUPEE_FIELDS:
            f["unit"] = "₹"
        if f["key"] in REMOVE_OPTIONS:
            gone = REMOVE_OPTIONS[f["key"]]
            missing = [o for o in gone if o not in f["options"]]
            assert not missing, f"{f['key']}: option(s) {missing} not in the Excel"
            f["options"] = [o for o in f["options"] if o not in gone]
        if f["key"] in ADD_OPTIONS:
            f["options"] = f["options"] + ADD_OPTIONS[f["key"]]
    # Credit flags go after the amounts; Litigation/Dispute (typed) goes last, after the documents.
    for keys, anchor in ((MOVE_TO_MONEY[:3], "monthly_emi"), (MOVE_TO_MONEY[3:], "bank_statements")):
        moved = [f for k in keys for f in fields if f["key"] == k]
        fields = [f for f in fields if f not in moved]
        at = next(i for i, f in enumerate(fields) if f["key"] == anchor) + 1
        for f in moved:
            f["section"] = "money"
        fields[at:at] = moved
    for add in ADD_FIELDS:
        at = next(i for i, f in enumerate(fields) if f["key"] == add["after"]) + 1
        fields.insert(at, {"excel_column": "new", "position": NEW_POSITIONS[add["field"]["key"]], **add["field"]})
    # Screen order inside each step follows the list order.
    counter: dict[str, int] = {}
    for f in fields:
        counter[f["section"]] = counter.get(f["section"], 0) + 1
        f["display_order"] = counter[f["section"]]
    return fields


def dropdowns_by_column(ws) -> dict[str, list[str]]:
    """Map column letter -> list options from the sheet's data validations."""
    result: dict[str, list[str]] = {}
    for dv in ws.data_validations.dataValidation:
        if dv.type != "list" or not dv.formula1:
            continue
        options = [o.strip() for o in dv.formula1.strip('"').split(",")]
        for rng in str(dv.sqref).split():
            cr = CellRange(rng)
            for col in range(cr.min_col, cr.max_col + 1):
                result[get_column_letter(col)] = options
    return result


def main() -> int:
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb["Lead Screening"]
    headers = [c.value for c in ws[1] if c.value is not None]
    if len(headers) != 44:
        print(f"Expected 44 headers, found {len(headers)}", file=sys.stderr)
        return 1
    if set(headers) != set(FIELD_MAP):
        print("Excel headers no longer match FIELD_MAP:", file=sys.stderr)
        print("  only in Excel:", sorted(set(headers) - set(FIELD_MAP)), file=sys.stderr)
        print("  only in map:  ", sorted(set(FIELD_MAP) - set(headers)), file=sys.stderr)
        return 1

    dropdowns = dropdowns_by_column(ws)
    section_order = {key: i for i, (key, _) in enumerate(SECTIONS, start=1)}
    # Order inside a step follows FIELD_MAP (the prototype's screen order).
    display_counter: dict[str, int] = {}
    display_order: dict[str, int] = {}
    for label, (_, _, section, _, _) in FIELD_MAP.items():
        display_counter[section] = display_counter.get(section, 0) + 1
        display_order[label] = display_counter[section]
    fields = []
    for position, label in enumerate(headers, start=1):
        key, ftype, section, unit, system_source = FIELD_MAP[label]
        col = get_column_letter(position)
        assert column_index_from_string(col) == position
        options = dropdowns.get(col)
        if ftype == "single_select" and not options:
            print(f"{label} mapped as single_select but has no dropdown", file=sys.stderr)
            return 1
        if options and ftype != "single_select":
            print(f"{label} has a dropdown but is mapped as {ftype}", file=sys.stderr)
            return 1
        fields.append(
            {
                "key": key,
                "label": label,
                "excel_column": col,
                "position": position,
                "field_type": ftype,
                "options": options,
                "unit": unit,
                "section": section,
                "display_order": display_order[label],
                "counts_toward_progress": ftype != "system",
                "system_source": system_source,
            }
        )

    fields = apply_client_changes(fields)
    out = {
        "version": 1,
        "source": EXCEL_PATH.name,
        "sections": [
            {"key": k, "label": lbl, "display_order": section_order[k]} for k, lbl in SECTIONS
        ],
        "fields": fields,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    progress = sum(f["counts_toward_progress"] for f in fields)
    print(f"Wrote {len(fields)} fields ({progress} count toward progress) to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
