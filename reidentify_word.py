#!/usr/bin/env python3
"""
reidentify_word.py

A command-line script to re-identify patient treatment plan Word documents (DOCX)
using local crosswalk CSV records.

USAGE:
    python reidentify_word.py <treatment_plan.docx> [case_code] [--output <output.docx>] [--crosswalk <crosswalk.csv>]
"""

import os
import sys
import csv
import argparse
import re
import zipfile
from pathlib import Path


def extract_case_code_from_string(text):
    """
    Finds the first Case ID matching standard datetime or custom patterns in the string.
    """
    if not text:
        return None
    patterns = [
        r"CASE-\d{4}[-_\s]\d{2}[-_\s]\d{2}[-_\s:]\d{2}[-_\s:]\d{2}[-_\s:]\d{2}", # Datetime format (time portion may use colons, e.g. "12:55:47")
        r"CASE-[A-Za-z0-9]+-[A-Za-z0-9]+",                                  # Segmented code
        r"CASE-[A-Za-z0-9]+"                                                # Basic code
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip("[] ")
    return None


def detect_case_code_from_docx(docx_path):
    """
    Scans the DOCX filename and text content to locate the deidentified Case ID.
    """
    # 1. Try finding pattern in filename
    code = extract_case_code_from_string(Path(docx_path).name)
    if code:
        return code
        
    # 2. Try finding pattern inside the XML text
    try:
        archive = zipfile.ZipFile(docx_path)
        xml_content = archive.read("word/document.xml").decode("utf-8")
        archive.close()
        text = re.sub(r'<[^>]+>', ' ', xml_content)
        code = extract_case_code_from_string(text)
        if code:
            return code
    except Exception as e:
        print(f"[-] Error detecting case code from DOCX text: {e}", file=sys.stderr)
        
    return None


def make_filename_safe(name):
    # Replace characters that are invalid in Windows/Linux filenames
    for char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', ' ']:
        name = name.replace(char, '_')
    return name


def find_crosswalk_file_flexibly(case_code, csv_path=None):
    """
    Finds a crosswalk CSV file matching case_code flexibly, ignoring spaces, hyphens, and underscores.
    """
    norm_case = re.sub(r'[^a-zA-Z0-9]', '', case_code).lower()
    
    search_dir = Path(csv_path) if csv_path and Path(csv_path).is_dir() else Path(".")
    
    # If csv_path points to a specific file, verify it
    if csv_path and Path(csv_path).is_file():
        return Path(csv_path)
        
    for p in search_dir.glob("*_crosswalk.csv"):
        # e.g., "CASE-2026-08-02_11_40_40_crosswalk.csv" -> stem is "CASE-2026-08-02_11_40_40"
        stem = p.name[:-14]
        norm_stem = re.sub(r'[^a-zA-Z0-9]', '', stem).lower()
        if norm_case == norm_stem:
            return p
            
    return None


def load_crosswalk(case_code, csv_path=None):
    """
    Locates and parses the crosswalk CSV for the given case code.
    Returns a dictionary of raw field -> value mappings, or None if not found.
    """
    csv_file = find_crosswalk_file_flexibly(case_code, csv_path)
    
    if not csv_file or not csv_file.exists():
        return None

    mappings = {}
    try:
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                field = row.get("field")
                val = row.get("original_value")
                if field and val:
                    mappings[field] = val
    except Exception as e:
        print(f"[-] Error reading crosswalk CSV: {e}", file=sys.stderr)
        return None

    return mappings


def parse_crosswalk_mappings(mappings):
    """
    Parses deidentification mappings to find Patient Name and DOB.
    """
    patient_name = mappings.get("patient_name_titlecase") or mappings.get("patient_name")
    patient_name_allcaps = mappings.get("patient_name_allcaps")
    
    # If no titlecase name, but we have allcaps, titlecase it
    if not patient_name and patient_name_allcaps:
        if "," in patient_name_allcaps:
            parts = [p.strip().title() for p in patient_name_allcaps.split(",")]
            if len(parts) == 2:
                patient_name = f"{parts[1]} {parts[0]}"
            else:
                patient_name = " ".join(parts)
        else:
            patient_name = patient_name_allcaps.title()
            
    # If no allcaps name, but we have titlecase, uppercase it
    if not patient_name_allcaps and patient_name:
        patient_name_allcaps = patient_name.upper()
        
    dob = (
        mappings.get("dob_long")
        or mappings.get("dob")
        or mappings.get("dob_slash")
        or mappings.get("dob_variant")
    )
    
    return {
        "name": patient_name,
        "name_allcaps": patient_name_allcaps,
        "dob": dob
    }


# Patient NAME is restored only via the literal case-code reference --
# "[CASE-2026-08-21-08-54-26]" or the bare case code. Every
# report_templates/*.py REPLACEMENT_MAP writes exactly this form in place
# of the name.
#
# As of 2026-08-23 this script does NOT restore DOB at all -- the
# treatment-plan drafting instructions now have Claude write an
# approximate age ("Age 64") instead of trying to reconstruct a real date
# of birth. This followed two rounds of DOB-related fragility: vendor
# date-format regexes that don't always match (some Optimal DX samples
# never even got a DOB extracted), and a same-day collision bug where a
# stray case-code reference sitting in the DOB field got matched by the
# name rule and produced "Lisa xyz | Age 64" -- the wrong value in the
# wrong field. Dropping DOB restoration removes that whole class of bug
# rather than patching it further. `deidentify_labs.py` still redacts DOB
# out of the uploaded PDF as before -- only the *restoration* step for the
# treatment plan was removed, not the original redaction.
#
# We deliberately do NOT guess at freeform phrasings like "De-Identified
# Patient" or "Jane Doe" either -- those were invented by whatever drafted
# the treatment plan, not by this pipeline, so matching them was never
# reliable. NAME_PLACEHOLDER_PATTERNS is kept only so
# find_leftover_placeholders() can flag one of these old-style phrasings if
# it's still sitting in the output -- a sign the drafting step didn't use
# the case-code marker and the document needs a human look, not a guess.
NAME_PLACEHOLDER_PATTERNS = [
    "De-Identified Patient", "De-identified Patient", "De-Identified patient",
    "De-identified patient", "DE-IDENTIFIED PATIENT", "de-identified patient",
    "Deidentified Patient", "Deidentified patient", "DEIDENTIFIED PATIENT",
    "deidentified patient", "Jane Doe", "JANE DOE", "jane doe",
]
ALL_PLACEHOLDER_PATTERNS = NAME_PLACEHOLDER_PATTERNS


def find_leftover_placeholders(text):
    """
    Returns the subset of ALL_PLACEHOLDER_PATTERNS still present in `text`.
    Intended for callers to check an already-written output document: if any
    of these are still present, replacement was incomplete (e.g. the source
    document used a placeholder phrasing this script doesn't map to the
    field that was actually available in the crosswalk) and the output
    should NOT be treated as a successful re-identification.
    """
    return [p for p in ALL_PLACEHOLDER_PATTERNS if p in text]


def reidentify_docx_file(docx_path, case_code, mappings, output_path=None):
    """
    Performs search and replace in the Word DOCX file and saves the result.

    Patient NAME is restored only where the document contains the literal
    case-code reference (e.g. "[CASE-2026-08-21-08-54-26]" or the bare case
    code) -- the one placeholder form the de-identification pipeline
    actually writes. DOB is not restored at all (see the module-level note
    above); the treatment plan is expected to carry only an approximate age.

    Returns:
        int  -- the number of placeholders actually replaced (0 means the file
                 was processed but nothing matched -- callers should treat that
                 as a failure, not a success, since the output would still show
                 placeholder text).
        None -- a hard error occurred (input missing, no name in the
                 crosswalk, or the DOCX couldn't be rewritten).
    """
    docx_file = Path(docx_path)
    if not docx_file.exists():
        print(f"[-] Error: Input DOCX file '{docx_path}' not found.", file=sys.stderr)
        return None

    info = parse_crosswalk_mappings(mappings)

    name = info.get("name")

    if not name:
        print("[-] Warning: No name mapping found in crosswalk. Nothing to restore.", file=sys.stderr)
        return None

    print("[+] Found Patient Details:")
    print(f"    - Name: {name}")

    replacements = []
    if name:
        # The only recognized name placeholder: the literal case-code
        # reference every template writes in place of the patient's name.
        replacements.extend([
            (f"[{case_code}]", name),
            (f"[{case_code.upper()}]", name.upper()),
            (case_code, name),
            (case_code.upper(), name.upper()),
        ])

    seen = set()
    unique_replacements = []
    for target, rep in replacements:
        if target and target not in seen:
            seen.add(target)
            unique_replacements.append((target, rep))
            
    unique_replacements.sort(key=lambda x: len(x[0]), reverse=True)

    print("[+] Replacement rules:")
    for target, replacement in unique_replacements:
        print(f"    - '{target}' -> '{replacement}'")

    total_replacements = 0
    try:
        archive = zipfile.ZipFile(str(docx_file), 'r')
        
        if not output_path:
            out_name = f"{docx_file.stem}_reidentified.docx"
            output_file = docx_file.parent / out_name
        else:
            output_file = Path(output_path)
            
        out_archive = zipfile.ZipFile(str(output_file), 'w', zipfile.ZIP_DEFLATED)
        
        for item in archive.infolist():
            data = archive.read(item.filename)
            if item.filename.endswith(".xml") or item.filename.endswith(".xml.rels"):
                text = data.decode("utf-8")
                modified = False
                for target, rep in unique_replacements:
                    if target in text:
                        count = text.count(target)
                        text = text.replace(target, rep)
                        total_replacements += count
                        modified = True
                data = text.encode("utf-8")
            out_archive.writestr(item, data)
            
        archive.close()
        out_archive.close()
    except Exception as e:
        print(f"[-] Error reidentifying DOCX file: {e}", file=sys.stderr)
        return None

    if total_replacements == 0:
        print("[-] Warning: No placeholder text found in the document.", file=sys.stderr)
    else:
        print(f"[+] Replaced {total_replacements} placeholders across the document.")

    print(f"[+] Success: Saved reidentified DOCX to: {output_file.name}")
    return total_replacements


def main():
    parser = argparse.ArgumentParser(
        description="Re-identify patient treatment plan Word documents (DOCX) using local crosswalk CSV records."
    )
    parser.add_argument("docx_path", help="Path to the de-identified DOCX file.")
    parser.add_argument(
        "case_code", 
        nargs="?", 
        default=None, 
        help="Case ID code associated with the patient. If omitted, it will be auto-detected from the file."
    )
    parser.add_argument("-o", "--output", help="Output path/filename for the reidentified DOCX.")
    parser.add_argument("-c", "--crosswalk", help="Path to specific crosswalk CSV file.")

    args = parser.parse_args()

    docx_path = Path(args.docx_path)
    if not docx_path.exists():
        print(f"[-] Error: File '{args.docx_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    case_code = args.case_code
    
    # 1. Try auto-detecting case code if not provided
    if not case_code:
        print("[+] Scanning file to auto-detect Case ID...")
        case_code = detect_case_code_from_docx(docx_path)
        if case_code:
            print(f"[+] Detected Case ID: {case_code}")
        else:
            print("[-] Error: Case code was not provided and could not be detected from the file.", file=sys.stderr)
            sys.exit(1)

    # 2. Load mappings
    mappings = load_crosswalk(case_code, args.crosswalk)
    
    # 3. Fallback: If mappings not found, try to auto-detect from file text in case of user typo
    if not mappings and args.case_code:
        detected = detect_case_code_from_docx(docx_path)
        if detected and detected != case_code:
            print(f"[!] Warning: Crosswalk CSV not found for entered Case ID '{case_code}'.")
            print(f"    Detected alternative Case ID '{detected}' inside the file. Trying that instead...")
            case_code = detected
            mappings = load_crosswalk(case_code, args.crosswalk)

    if not mappings:
        print(f"[-] Error: Could not locate crosswalk CSV for Case ID '{case_code}'.", file=sys.stderr)
        sys.exit(1)

    replaced = reidentify_docx_file(docx_path, case_code, mappings, args.output)
    if not replaced:
        sys.exit(1)


if __name__ == "__main__":
    main()
