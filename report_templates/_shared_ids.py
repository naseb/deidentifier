"""
Shared ID/phone-label extraction used by more than one report template.

These label formats ("Patient ID:", "Health ID:", etc.) were originally
matched unconditionally against every document in deidentify_labs.py, before
this project supported more than the Optimal DX and Quest templates. Kept
here, unchanged, so both of those templates continue to behave exactly as
before now that each template only runs after its own detect() has matched.
"""

import re

# label -> (regex, output key)
LABELED_ID_PATTERNS = [
    ("patient_id", r"Patient ID:\s*(\S+)"),
    ("health_id", r"Health ID:\s*(\S+)"),
    ("specimen_id", r"Specimen:\s*(\S+)"),
    ("requisition_id", r"Requisition:\s*(\S+)"),
    ("patient_phone", r"Phone:\s*([\d.\-() ]{7,})"),
]


def extract_labeled_ids(full_text: str) -> dict:
    found = {}
    for label, pattern in LABELED_ID_PATTERNS:
        m = re.search(pattern, full_text)
        if m:
            found[label] = m.group(1).strip()
    return found
