#!/usr/bin/env python3
"""
deidentify_labs.py

Run this LOCALLY (on Danielle's computer, with Python installed) on lab report
PDFs BEFORE any file is uploaded to Claude or any other cloud tool. This
script never sends anything anywhere — it only reads a local PDF and writes a
local PDF + a local crosswalk file.

WHAT IT DOES
------------
1. Finds known patient-identifying fields in the PDF (name, DOB, patient/health/
   specimen/requisition IDs, patient phone number) using PyMuPDF's true redaction
   (this REMOVES the underlying text, not just draws a box over it — a plain
   black rectangle drawn on top of text is not real redaction, because the
   original text is still selectable/extractable underneath it).
2. Replaces each occurrence with a case code you choose (e.g. "CASE-2026-0731-A").
3. Writes:
     <original>_deidentified.pdf   -> safe to upload to Claude
     <original>_crosswalk.csv      -> KEEP THIS LOCAL. Never upload it anywhere.
                                       It's the only thing that maps the case
                                       code back to the real patient.

WHAT IT DOES NOT DO
--------------------
- It does not touch clinical content (lab values, ranges, dysfunction scores,
  recommendations) — only the identifying fields each report template below.
- It does not generalize collection/received/reported dates by default (see
  the DATE HANDLING note below) — decide with your compliance advisor whether
  your use case requires that.
- It only recognizes the specific report *templates* registered in
  report_templates/ (see that package's __init__.py for the current list and
  for how to add a new lab company). A PDF that doesn't match any registered
  template is left untouched and reported as unmatched — it will NOT be
  guessed at, so it's your job to route it to manual review rather than
  upload it as-is.

DATE HANDLING
-------------
HIPAA's Safe Harbor de-identification standard treats ALL elements of a date
(other than year) tied to an individual as an identifier — including the
collection date. This script leaves dates as-is by default because clinical
recency often matters for a treatment-plan draft. If your compliance advisor
tells you dates need to be removed/generalized too, add them to IDENTIFIERS
below the same way the other fields are handled, or ask for a "date-shifting"
version that offsets every date by the same random number of days per case
(preserves the gap between draws without revealing real dates).

USAGE
-----
    python3 deidentify_labs.py <case_code> <input.pdf> [<input2.pdf> ...]

Example:
    python3 deidentify_labs.py CASE-2026-0731-A OptimalDX_Report.pdf Quest_Labs.pdf
"""

import sys
import csv
import re
import datetime
from pathlib import Path

import fitz  # PyMuPDF

from report_templates import find_identifiers_for_doc


def make_filename_safe(name):
    # Replace characters that are invalid in Windows/Linux filenames
    for char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', ' ']:
        name = name.replace(char, '_')
    return name


def format_case_code_for_filename(case_code):
    # Convert spaces, underscores, colons, and slashes to hyphens
    formatted = re.sub(r'[\\/:*?"<>|_\s]+', '-', case_code)
    # Remove duplicate hyphens
    formatted = re.sub(r'-+', '-', formatted)
    return formatted.strip('-')


def remove_patient_name_from_filename(filename, patient_name):
    if not patient_name:
        return filename
        
    # Remove extension first to avoid replacing anything in it
    stem = Path(filename).stem
    ext = Path(filename).suffix
    
    # Generate terms to remove: full name and individual names
    terms = [patient_name]
    
    # Split name into words and add them
    words = [w.strip() for w in re.split(r'[^a-zA-Z]', patient_name) if len(w.strip()) > 2]
    terms.extend(words)
    
    # Also add comma-separated if name was "Last, First"
    if "," in patient_name:
        parts = [p.strip() for p in patient_name.split(",")]
        terms.extend(parts)
        
    # Unique and sort by length descending
    unique_terms = sorted(list(set(terms)), key=len, reverse=True)
    
    for term in unique_terms:
        # Case insensitive replacement of term in the stem
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        stem = pattern.sub("", stem)
        
    # Clean up any leftover duplicate separators in the stem
    stem = re.sub(r'[-_\s]+', '-', stem)
    stem = stem.strip('-_ ')
    
    # Fallback if stem is empty
    if not stem:
        stem = "report"
        
    return f"{stem}{ext}"


def get_all_known_patient_names(directory):
    names = set()
    try:
        for p in Path(directory).glob("*_crosswalk.csv"):
            with open(p, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    field = row.get("field")
                    val = row.get("original_value")
                    if field in [
                        "patient_name", "patient_name_titlecase", "patient_name_allcaps",
                        "patient_first_name", "patient_last_name",
                    ] and val:
                        names.add(val.strip())
    except Exception:
        pass
    return list(names)


def clean_filename_fully(filename, patient_name, directory=None):
    cleaned = filename
    if patient_name:
        cleaned = remove_patient_name_from_filename(cleaned, patient_name)
        
    if directory:
        known_names = get_all_known_patient_names(directory)
        for name in known_names:
            cleaned = remove_patient_name_from_filename(cleaned, name)
            
    # Prevent double suffix by removing existing "_deidentified"
    stem = Path(cleaned).stem
    ext = Path(cleaned).suffix
    
    if stem.endswith("_deidentified"):
        stem = stem[:-13]
    elif stem.endswith("-deidentified"):
        stem = stem[:-13]
        
    return f"{stem}{ext}"



def redact_value(doc, value, replacement):
    """True redaction: removes the underlying text object, not just a visual
    overlay. Applies across every page the value appears on.

    text_color is explicitly set to white: add_redact_annot's text_color
    defaults to black, same as the black fill box, which silently renders
    the replacement text invisible (present in the extractable text layer,
    but not visible to a human or a vision-reading model looking at the
    page -- see CLAUDE.md, "invisible placeholder text" bug, 2026-08-23)."""
    if not value:
        return 0
    count = 0
    for page in doc:
        instances = page.search_for(value)
        for inst in instances:
            page.add_redact_annot(inst, text=replacement, fill=(0, 0, 0), text_color=(1, 1, 1))
            count += 1
        if instances:
            page.apply_redactions()
    return count


def process_pdf_doc(doc, filename: str, case_code: str, crosswalk_rows: list):
    """
    Process a fitz.Document object, perform redactions, and return the identified
    fields and total redaction count. Which fields get looked for at all is
    decided by report_templates.find_identifiers_for_doc, which tries each
    known lab-report template in turn and uses the first one that matches
    (see report_templates/__init__.py).
    """
    identifiers, replacement_map, template_name = find_identifiers_for_doc(doc)

    if not identifiers:
        print(f"  ! No known report template matched {filename} — "
              f"check it's a supported lab format, and verify manually before uploading.")
    else:
        print(f"  Found in {filename} (template: {template_name}):")
        for label, value in identifiers.items():
            print(f"    - {label}: {value}")

    total_redactions = 0
    for label, value in identifiers.items():
        replacement_template = replacement_map.get(label, "[REDACTED]")
        replacement = replacement_template.format(case_code=case_code)
        n = redact_value(doc, value, replacement)
        total_redactions += n
        crosswalk_rows.append({
            "source_file": filename,
            "case_code": case_code,
            "field": label,
            "original_value": value,
            "occurrences_redacted": n,
        })

    return identifiers, total_redactions


def patient_name_from_identifiers(identifiers: dict):
    """Best-effort full patient name for filename cleanup, regardless of
    which report template's field names produced it."""
    if identifiers.get("patient_first_name") or identifiers.get("patient_last_name"):
        return f"{identifiers.get('patient_first_name', '')} {identifiers.get('patient_last_name', '')}".strip()
    return (
        identifiers.get("patient_name")
        or identifiers.get("patient_name_titlecase")
        or identifiers.get("patient_name_allcaps")
    )


def process_pdf(path: Path, case_code: str, crosswalk_rows: list):
    doc = fitz.open(str(path))
    identifiers, total_redactions = process_pdf_doc(doc, path.name, case_code, crosswalk_rows)

    patient_name = patient_name_from_identifiers(identifiers)
    safe_case = format_case_code_for_filename(case_code)
    cleaned_filename = clean_filename_fully(path.name, patient_name, path.parent)
    out_name = f"{safe_case}-{Path(cleaned_filename).stem}_deidentified.pdf"
    
    out_path = Path(out_name)
    doc.save(str(out_path))
    doc.close()
    print(f"  -> Wrote {out_path.name} ({total_redactions} redactions applied)")
    return out_path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    first_arg = sys.argv[1]
    # Check if the first argument is a PDF file or exists, meaning case_code was omitted
    if first_arg.lower().endswith(".pdf") or Path(first_arg).exists():
        case_code = datetime.datetime.now().strftime("CASE-%Y-%m-%d %H:%M:%S")
        input_paths = [Path(p) for p in sys.argv[1:]]
    else:
        case_code = first_arg
        input_paths = [Path(p) for p in sys.argv[2:]]

    if not input_paths:
        print("Error: No input PDF files specified.")
        print(__doc__)
        sys.exit(1)

    crosswalk_rows = []
    print(f"De-identifying under case code: {case_code}\n")
    for p in input_paths:
        if not p.exists():
            print(f"  ! Skipping {p} — file not found")
            continue
        process_pdf(p, case_code, crosswalk_rows)
        print()

    if crosswalk_rows:
        safe_case_code = make_filename_safe(case_code)
        crosswalk_path = Path(f"{safe_case_code}_crosswalk.csv")
        with open(crosswalk_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "source_file", "case_code", "field", "original_value", "occurrences_redacted"
            ])
            writer.writeheader()
            writer.writerows(crosswalk_rows)
        print(f"Wrote {crosswalk_path} — KEEP THIS FILE LOCAL. Do not upload it anywhere.")

    print("\nNext: open each *_deidentified.pdf and visually confirm no identifying")
    print("text remains before uploading anything to Claude.")


if __name__ == "__main__":
    main()
