"""
US BioTek / GI-Advanced Profile Laboratory Report Template.

Identifies:
- Patient Name (TitleCase and ALLCAPS)
- First Name and Last Name
- Comma-separated Name format (Last, First)
- Date of Birth (DD-Mon-YY and variants)
- Order ID, Requisition ID, Account ID
- Phone number
"""

import re

NAME = "us_biotek"

REPLACEMENT_MAP = {
    "patient_name": "[{case_code}]",
    "patient_name_allcaps": "[{case_code}]",
    "patient_name_comma": "[{case_code}]",
    "patient_first_name": "[REDACTED]",
    "patient_last_name": "[REDACTED]",
    "dob": "[REDACTED]",
    "dob_slash": "[REDACTED]",
    "patient_phone": "[REDACTED]",
    "requisition_id": "[REDACTED]",
    "order_id": "[REDACTED]",
    "account_id": "[REDACTED]",
}

_SEX_BLOCK_PATTERN = re.compile(
    r"([A-Za-z\s\'-]+)\nSex:\s*(?:Female|Male|Other)\n\d+\s*yrs\n(\d{1,2}-[A-Za-z]{3}-\d{2,4})",
    re.IGNORECASE
)

_REQ_PATTERN = re.compile(r"Req ID\s*\n\s*(\d+)", re.IGNORECASE)
_ORDER_PATTERN = re.compile(r"Order ID\s*\n\s*(\d+)", re.IGNORECASE)
_ACCOUNT_PATTERN = re.compile(r"Account ID\s*\n\s*([A-Za-z0-9\-]+)", re.IGNORECASE)
_PHONE_PATTERN = re.compile(r"Tel ID\s*\n\s*([\d\s\-()]+)", re.IGNORECASE)

def detect(doc, full_text: str, page1_text: str) -> bool:
    """
    Detects US BioTek or GI-Advanced / GI-Pathogen profiles based on CLIA,
    profile headers, or laboratory branding.
    """
    p1_lower = page1_text.lower()
    full_lower = full_text.lower()
    
    return (
        "gi-advanced" in p1_lower
        or "gi-pathogen" in p1_lower
        or "us biotek" in p1_lower
        or "us biotek" in full_lower
        or "clia#99d" in p1_lower
        or ("gi-advanced" in full_lower and "clia" in full_lower)
    )

def extract(doc, full_text: str, page1_text: str) -> dict:
    """
    Extracts patient identifying information from US BioTek / GI-Advanced reports.
    """
    found = {}

    # Extract Name, Sex, Age, DOB from Page 1 Header Block
    m = _SEX_BLOCK_PATTERN.search(page1_text)
    if m:
        raw_name = m.group(1).strip()
        clean_name = re.sub(r"^[^\w]+|[^\w]+$", "", raw_name)
        if clean_name:
            found["patient_name"] = clean_name
            found["patient_name_allcaps"] = clean_name.upper()
            
            parts = clean_name.split()
            if len(parts) >= 2:
                first = parts[0]
                last = parts[-1]
                found["patient_first_name"] = first
                found["patient_last_name"] = last
                found["patient_name_comma"] = f"{last}, {first}"
                
        raw_dob = m.group(2).strip()
        if raw_dob:
            found["dob"] = raw_dob

    # Fallback search for DOB in standard formats if not captured
    if "dob" not in found:
        dob_m = re.search(r"DOB:\s*(\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-[A-Za-z]{3}-\d{2,4})", page1_text, re.IGNORECASE)
        if dob_m:
            found["dob"] = dob_m.group(1).strip()

    # Requisition ID
    req_m = _REQ_PATTERN.search(page1_text)
    if req_m:
        found["requisition_id"] = req_m.group(1).strip()

    # Order ID
    order_m = _ORDER_PATTERN.search(page1_text)
    if order_m:
        found["order_id"] = order_m.group(1).strip()

    # Account ID
    acc_m = _ACCOUNT_PATTERN.search(page1_text)
    if acc_m:
        found["account_id"] = acc_m.group(1).strip()

    # Phone
    phone_m = _PHONE_PATTERN.search(page1_text)
    if phone_m:
        found["patient_phone"] = phone_m.group(1).strip()

    return found
