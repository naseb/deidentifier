"""
NutriPATH-branded Genova Organic Acids Profile report (e.g. filenames like
"<order>-N_OAP62-<patient>.pdf").

Every page repeats a footer/header identity block in this order:
    <barcode-like ID>
    <practitioner name>            <- NOT redacted; this is the ordering
                                       practitioner, not the patient (HIPAA
                                       Safe Harbor covers patient identifiers,
                                       not the treating clinician's identity)
    Order ID
    <id>
    Lab ID
    <id>
    Patient ID <id>                <- inline, no colon
    Ext ID
    <id>
    Alt ID
    <id>
    <Patient Full Name>            <- Title Case, two words, unlabeled
    Sex: <Male/Female>
    <NN>yrs
    <DOB, e.g. 12-Nov-76>          <- unlabeled, immediately after age
    RECEIVED
    <received date>
    ...
    Lab Director: ... Testing performed by NutriPATH, <address>

Detected via the "NutriPATH" brand string, which is distinct enough not to
collide with the Quest or Optimal DX templates.
"""

import re

NAME = "genova_oap_nutripath"

REPLACEMENT_MAP = {
    "patient_name_titlecase": "[{case_code}]",
    "dob_dd_mon_yy": "[REDACTED]",
    "patient_id": "[REDACTED]",
    "order_id": "[REDACTED]",
    "lab_id": "[REDACTED]",
    "ext_id": "[REDACTED]",
    "alt_id": "[REDACTED]",
}

_PATIENT_ID_PATTERN = r"Patient ID\s+(\S+)"
_ORDER_ID_PATTERN = r"Order ID\s*\n(\S+)"
_LAB_ID_PATTERN = r"Lab ID\s*\n(\S+)"
_EXT_ID_PATTERN = r"Ext ID\s*\n(\S+)"
_ALT_ID_PATTERN = r"Alt ID\s*\n(\S+)\s*\n([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)+)\s*\nSex:"
_DOB_PATTERN = r"\d+yrs\s*\n(\d{1,2}-[A-Za-z]{3,9}-\d{2,4})\s*\nRECEIVED"


def detect(doc, full_text: str, page1_text: str) -> bool:
    return "NutriPATH" in full_text and bool(re.search(_PATIENT_ID_PATTERN, full_text))


def extract(doc, full_text: str, page1_text: str) -> dict:
    found = {}

    m = re.search(_PATIENT_ID_PATTERN, full_text)
    if m:
        found["patient_id"] = m.group(1).strip()

    m = re.search(_ORDER_ID_PATTERN, full_text)
    if m:
        found["order_id"] = m.group(1).strip()

    m = re.search(_LAB_ID_PATTERN, full_text)
    if m:
        found["lab_id"] = m.group(1).strip()

    m = re.search(_EXT_ID_PATTERN, full_text)
    if m:
        found["ext_id"] = m.group(1).strip()

    m = re.search(_ALT_ID_PATTERN, full_text)
    if m:
        found["alt_id"] = m.group(1).strip()
        found["patient_name_titlecase"] = m.group(2).strip()

    m = re.search(_DOB_PATTERN, full_text)
    if m:
        found["dob_dd_mon_yy"] = m.group(1)

    return found
