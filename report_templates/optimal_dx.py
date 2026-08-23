"""
Optimal DX Functional Health Report / Practitioner Report template.

Patient name is printed as "Prepared for\\n<First Last>" -- but the
"Prepared for" label text has been observed in both mixed case and ALL CAPS
across different report brandings (e.g. "PREPARED FOR" in a report seen
2026-08-23), so label matching is case-insensitive; the captured name value
itself must still be normal Title Case, which is unaffected by that flag.

DOB, when present, is printed as "born <Month DD, YYYY>" and still gets
extracted/redacted if found -- but detect() no longer REQUIRES a DOB match,
because a report variant seen 2026-08-23 prints only an age ("49 year old
female") with no literal date of birth anywhere in the document at all.
Requiring DOB would make this template permanently unable to detect that
variant, regardless of case-sensitivity. Detection specificity instead
comes from pairing the name pattern with a brand/product-name anchor
("Functional Health Report" / "Practitioner Report" -- generic marketing
copy, not patient data) so this template still can't accidentally fire on
another lab's report.
"""

import re

from ._shared_ids import extract_labeled_ids

NAME = "optimal_dx"

REPLACEMENT_MAP = {
    "patient_name_titlecase": "[{case_code}]",
    "dob_long": "[REDACTED]",
    "patient_id": "[REDACTED]",
    "health_id": "[REDACTED]",
    "specimen_id": "[REDACTED]",
    "requisition_id": "[REDACTED]",
    "patient_phone": "[REDACTED]",
}

_NAME_PATTERN = r"Prepared for\s*\n?\s*([A-Z][a-zA-Z'\-]+ [A-Z][a-zA-Z'\-]+)"
_DOB_PATTERN = r"born\s+([A-Za-z]{3,9}\.?\s+\d{1,2},\s+\d{4})"
_BRAND_PATTERN = r"Functional Health Report|Practitioner Report"


def detect(doc, full_text: str, page1_text: str) -> bool:
    return (bool(re.search(_NAME_PATTERN, full_text, re.IGNORECASE))
            and bool(re.search(_BRAND_PATTERN, full_text, re.IGNORECASE)))


def extract(doc, full_text: str, page1_text: str) -> dict:
    found = {}

    m = re.search(_NAME_PATTERN, full_text, re.IGNORECASE)
    if m:
        found["patient_name_titlecase"] = m.group(1).strip()

    # Optional -- not every report variant prints a literal DOB (see module
    # docstring). Still redacted if present; simply omitted if not.
    m = re.search(_DOB_PATTERN, full_text, re.IGNORECASE)
    if m:
        found["dob_long"] = m.group(1)

    found.update(extract_labeled_ids(full_text))
    return found
