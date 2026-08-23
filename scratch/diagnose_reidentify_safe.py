#!/usr/bin/env python3
"""
diagnose_reidentify_safe.py

PII-safe diagnostic for a specific re-identification case. Loads the real
crosswalk values (name/DOB) into memory to test for their presence, but
NEVER prints them -- only booleans, occurrence counts, and XML part names
(all safe: no patient data).

Usage:
    python scratch/diagnose_reidentify_safe.py <CASE-CODE>
"""

import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reidentify_word import load_crosswalk, parse_crosswalk_mappings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

PLACEHOLDER_PATTERNS = [
    "De-Identified Patient", "De-identified Patient", "De-Identified patient",
    "De-identified patient", "DE-IDENTIFIED PATIENT", "de-identified patient",
    "Deidentified Patient", "Deidentified patient", "DEIDENTIFIED PATIENT",
    "deidentified patient", "Jane Doe", "JANE DOE", "jane doe",
    "De-Identified", "De-identified", "DE-IDENTIFIED", "de-identified",
    "Deidentified", "DEIDENTIFIED", "deidentified",
]


def xml_parts_text(docx_path):
    """Yields (member_name, text) for every xml part in the docx."""
    with zipfile.ZipFile(docx_path) as z:
        for info in z.infolist():
            if info.filename.endswith(".xml") or info.filename.endswith(".xml.rels"):
                data = z.read(info.filename).decode("utf-8", errors="replace")
                text = re.sub(r"<[^>]+>", " ", data)
                yield info.filename, text


def scan_file(label, path, name, name_allcaps, dob, case_code):
    if not path.exists():
        print(f"[{label}] file not found: (path omitted)")
        return
    print(f"[{label}] scanning {path.name}")
    any_name = False
    any_dob = False
    any_placeholder_hits = {}
    any_case_code = False
    for member, text in xml_parts_text(path):
        hits = []
        if name and name in text:
            any_name = True
            hits.append("REAL_NAME")
        if name_allcaps and name_allcaps in text:
            any_name = True
            hits.append("REAL_NAME_ALLCAPS")
        if dob and dob in text:
            any_dob = True
            hits.append("REAL_DOB")
        if case_code and case_code in text:
            any_case_code = True
            hits.append("CASE_CODE_LITERAL")
        for pat in PLACEHOLDER_PATTERNS:
            c = text.count(pat)
            if c:
                any_placeholder_hits[pat] = any_placeholder_hits.get(pat, 0) + c
                hits.append(f"placeholder:'{pat}' x{c}")
        if hits:
            print(f"    - {member}: {', '.join(hits)}")
    print(f"[{label}] summary: real_name_found={any_name} real_dob_found={any_dob} "
          f"literal_case_code_found={any_case_code} "
          f"placeholder_patterns_found={list(any_placeholder_hits.keys())}")
    print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_reidentify_safe.py <CASE-CODE>")
        sys.exit(1)
    case_code = sys.argv[1]

    mappings = load_crosswalk(case_code, str(REPO_ROOT))
    if not mappings:
        print(f"No crosswalk found for case code '{case_code}' in {REPO_ROOT}")
        sys.exit(1)

    info = parse_crosswalk_mappings(mappings)
    name = info.get("name")
    name_allcaps = info.get("name_allcaps")
    dob = info.get("dob")

    print(f"Crosswalk loaded for {case_code}. Fields present (not values): "
          f"name={bool(name)} name_allcaps={bool(name_allcaps)} dob={bool(dob)}")
    print(f"All crosswalk field labels on file: {sorted(mappings.keys())}\n")

    archive_matches = sorted(
        (REPO_ROOT / "Treatment Plans - Archive").glob(f"{case_code}*.docx")
    )
    ready_matches = sorted(
        (REPO_ROOT / "Treatment Plans - Patient Ready").glob(f"{case_code}*reidentified*.docx")
    )

    for p in archive_matches:
        scan_file("ARCHIVE (pre-reidentify, de-identified version)", p, name, name_allcaps, dob, case_code)
    for p in ready_matches:
        scan_file("PATIENT READY (post-reidentify output)", p, name, name_allcaps, dob, case_code)

    if not archive_matches:
        print("No matching file found in Treatment Plans - Archive for this case code.")
    if not ready_matches:
        print("No matching file found in Treatment Plans - Patient Ready for this case code.")


if __name__ == "__main__":
    main()
