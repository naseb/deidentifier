"""
ZRT Laboratory report template.

Patient name is printed next to a 👤 icon in the running header of each page,
and in the body as "Patient Name: <First Last>".
DOB is printed under "DOB" as "MM/DD/YYYY (Age yrs)".
Requisition ID is printed starting with "# <YYYY MM DD ...>".
Accession code is printed as "ord_<ID>".
"""

import re

NAME = "zrt"

REPLACEMENT_MAP = {
    "patient_name": "[{case_code}]",
    "patient_name_comma": "[{case_code}]",
    "patient_first_name": "[REDACTED]",
    "patient_last_name": "[REDACTED]",
    "dob": "[REDACTED]",
    "patient_phone": "[REDACTED]",
    "requisition_id": "[REDACTED]",
    "accession_id": "[REDACTED]",
}

_NAME_PATTERN = r"Patient Name:\s*([A-Za-z][a-zA-Z'\-]+(?:\s+[A-Za-z][a-zA-Z'\-]+)+)"
_PHONE_PATTERN = r"Patient Phone Number:\s*([\d\s\-()]+)"
_DOB_PATTERN = r"DOB\s*\n?\s*(\d{1,2}/\d{1,2}/\d{4})"
_REQ_PATTERN = r"#\s*(\d{4}\s+\d{2}\s+\d{2}\s+[\d\s]+[A-Za-z])"
_ACC_PATTERN = r"\b(ord_[A-Za-z0-9]+)\b"

def detect(doc, full_text: str, page1_text: str) -> bool:
    # Detect based on CLIA license or trademark logo text
    return "ZRT Laboratory" in full_text or "ZRT Lab" in full_text

def extract(doc, full_text: str, page1_text: str) -> dict:
    found = {}

    m = re.search(_NAME_PATTERN, full_text)
    if m:
        name = m.group(1).strip()
        found["patient_name"] = name
        # Split first/last and add comma-separated representation for full redaction coverage
        parts = name.split(None, 1)
        if len(parts) == 2:
            first, last = parts
            found["patient_first_name"] = first
            found["patient_last_name"] = last
            found["patient_name_comma"] = f"{last}, {first}"

    m = re.search(_DOB_PATTERN, full_text)
    if m:
        found["dob"] = m.group(1).strip()

    m = re.search(_PHONE_PATTERN, full_text)
    if m:
        found["patient_phone"] = m.group(1).strip()

    m = re.search(_REQ_PATTERN, full_text)
    if m:
        found["requisition_id"] = m.group(1).strip()

    m = re.search(_ACC_PATTERN, full_text)
    if m:
        found["accession_id"] = m.group(1).strip()

    return found
