"""
Quest Diagnostics report template.

Patient name is printed ALLCAPS as "<LAST>, <FIRST>" near "DOB:" on page 1.
DOB is "DOB: MM/DD/YYYY". Also carries the labeled ID block (Patient ID,
Health ID, Specimen, Requisition, Phone) plus a "Lab Ref #:" field seen on
newer Quest reports.
"""

import re

from ._shared_ids import extract_labeled_ids

NAME = "quest"

REPLACEMENT_MAP = {
    "patient_name_allcaps": "[{case_code}]",
    "dob_slash": "[REDACTED]",
    "patient_id": "[REDACTED]",
    "health_id": "[REDACTED]",
    "specimen_id": "[REDACTED]",
    "requisition_id": "[REDACTED]",
    "patient_phone": "[REDACTED]",
    "lab_ref_id": "[REDACTED]",
}

# ALLCAPS "LAST, FIRST" followed (within 100 chars) by "DOB:" -- scoped to
# page 1 only to avoid matching an unrelated ALLCAPS-comma-ALLCAPS pair
# elsewhere in the clinical content (e.g. "VLDL, IDL" in a lipid panel).
_NAME_PATTERN = r"\b([A-Z][A-Z'\-]+),\s*([A-Z][A-Z'\-]+)\b[\s\S]{0,100}?DOB:"
_DOB_PATTERN = r"DOB:\s*(\d{2}/\d{2}/\d{4})"
_LAB_REF_PATTERN = r"Lab Ref #:\s*\n?\s*(\S+)"


def detect(doc, full_text: str, page1_text: str) -> bool:
    return bool(re.search(_NAME_PATTERN, page1_text)) and bool(re.search(_DOB_PATTERN, full_text))


def extract(doc, full_text: str, page1_text: str) -> dict:
    found = {}

    m = re.search(_NAME_PATTERN, page1_text)
    if m:
        found["patient_name_allcaps"] = f"{m.group(1)}, {m.group(2)}"

    m = re.search(_DOB_PATTERN, full_text)
    if m:
        found["dob_slash"] = m.group(1)

    m = re.search(_LAB_REF_PATTERN, full_text)
    if m:
        found["lab_ref_id"] = m.group(1).strip()

    found.update(extract_labeled_ids(full_text))
    return found
