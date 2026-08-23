"""
Genova Diagnostics breath test report (e.g. SIBO 3-Hour Breath test).

Page 1 header carries:
    Order Number: <id>
    Reported: <Month DD, YYYY>
    Received: <Month DD, YYYY>
    Collected: <Month DD, YYYY>
    Route Number: ord_xxxxxxx      <- internal order routing, NOT redacted
                                       (administrative code, not a patient
                                       identifier -- same treatment as
                                       "Test Codes:" in the NutriPATH template)
    MRN: <id>
    Sex: <M/F>
    DOB: <Month DD, YYYY>
    <LASTNAME>                     <- standalone ALLCAPS line, no comma
    <FIRSTNAME>                    <- standalone ALLCAPS line, no comma
    Patient: ...
    Unless otherwise noted, testing performed by (c) Genova Diagnostics,
    <address>, Asheville, NC ... CLIA Lic. #...

PyMuPDF's page.search_for() is case-insensitive (verified locally), so
redacting the ALLCAPS last/first name found here also removes any
Title Case rendering of the same name elsewhere in the document (e.g. the
"Patient: <Name> <page#>" header repeated on pages 2+) without needing to
parse that more ambiguous, column-jumbled line directly.

Detected via "Genova Diagnostics" + "MRN:" + "Order Number:", which does not
collide with the NutriPATH-branded Organic Acids template (different labels,
different brand string) even though both ultimately trace back to Genova.
"""

import re

NAME = "genova_sibo"

REPLACEMENT_MAP = {
    "patient_last_name": "[{case_code}]",
    "patient_first_name": "[{case_code}]",
    "dob_month_dd_yyyy": "[REDACTED]",
    "order_number": "[REDACTED]",
    "mrn": "[REDACTED]",
}

_ORDER_NUMBER_PATTERN = r"Order Number:\s*(\S+)"
_MRN_PATTERN = r"MRN:\s*(\S+)"
_DOB_PATTERN = r"DOB:\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})"
# Two standalone ALLCAPS lines back-to-back, immediately followed by the
# "Patient:" label -- this is how the last/first name is printed on page 1.
_NAME_PATTERN = r"\n([A-Z][A-Z'\-]{1,19})\s*\n([A-Z][A-Z'\-]{1,19})\s*\nPatient:"


def detect(doc, full_text: str, page1_text: str) -> bool:
    return (
        "Genova Diagnostics" in full_text
        and bool(re.search(_MRN_PATTERN, full_text))
        and bool(re.search(_ORDER_NUMBER_PATTERN, full_text))
    )


def extract(doc, full_text: str, page1_text: str) -> dict:
    found = {}

    m = re.search(_ORDER_NUMBER_PATTERN, full_text)
    if m:
        found["order_number"] = m.group(1).strip()

    m = re.search(_MRN_PATTERN, full_text)
    if m:
        found["mrn"] = m.group(1).strip()

    m = re.search(_DOB_PATTERN, full_text)
    if m:
        found["dob_month_dd_yyyy"] = m.group(1)

    m = re.search(_NAME_PATTERN, page1_text)
    if m:
        found["patient_last_name"] = m.group(1).strip()
        found["patient_first_name"] = m.group(2).strip()

    return found
