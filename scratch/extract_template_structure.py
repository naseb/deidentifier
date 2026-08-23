#!/usr/bin/env python3
"""
extract_template_structure.py

Run this LOCALLY yourself. It reads a lab report PDF and writes a text file
showing the page LAYOUT and field LABELS (e.g. "Patient Name:", "DOB:",
"Requisition #:") with the actual identifying VALUES replaced by a
SHAPE-PRESERVING placeholder — so the structure and format can be shared with
Claude to design a new template, without any real patient data ever leaving
your machine.

Shape-preserving means the placeholder shows the FORMAT of the real value,
not the value itself: every uppercase letter becomes 'X', every lowercase
letter becomes 'x', every digit becomes '9', and all punctuation/spacing is
left as-is. So a DOB like "12-Nov-76" becomes "99-Xxx-99", and an ID like
"P071963" becomes "X999999". This is still zero real data, but tells Claude
exactly what pattern to write a regex against.

Masking is intentionally aggressive/over-inclusive here (unlike the real
de-identifier, which must NOT over-redact clinical content). This script's
only job is to produce something safe to hand to an LLM, so it's fine if it
also blanks out things that turn out to be harmless -- worst case is some
noise in the output, not a leaked value.

Masks:
    - dates (multiple formats)               -> [DATE:<shape>]
    - times                                   -> [TIME:<shape>]
    - phone numbers                           -> [PHONE:<shape>]
    - SSN-shaped numbers                      -> [SSN:<shape>]
    - email addresses                         -> [EMAIL:<shape>]
    - long digit runs (5+ digits)             -> [ID#:<shape>]
    - alphanumeric ID/specimen codes          -> [ID#:<shape>]
    - street-address-shaped lines             -> [ADDRESS:<shape>]
    - "LAST, FIRST" ALLCAPS name shape        -> [NAME?:<shape>]
    - standalone ALLCAPS word alone on a line -> [NAME?:<shape>]
      (catches "LAST"/"FIRST" printed on separate lines with no comma)
    - Capitalized word pairs/triples right after label words like
      "Patient", "Name", "Prepared for", "Member" -> [NAME?:<shape>]
    - any extra literal strings you already know are real (patient name,
      etc.) passed via --known -> [KNOWN:<shape>]

USAGE
-----
    python extract_template_structure.py <input.pdf> [<input2.pdf> ...] [--known "Lisa McQuillen,McQuillen"]

Output lands in:  scratch/structure_review/<original_filename>.txt

IMPORTANT: Open each output file yourself and confirm nothing looks like a
readable real name, DOB, or ID slipped through before sharing it with
anyone/anything else. Every placeholder should look like scrambled
X/x/9 characters, never actual readable text.
"""

import re
import argparse
from pathlib import Path

import fitz  # PyMuPDF

OUT_DIR = Path(__file__).parent / "structure_review"

DATE_PATTERNS = [
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}\b",
    r"\b\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}\b",
    r"\b\d{1,2}-[A-Za-z]{3,9}-\d{2,4}\b",  # e.g. 12-Nov-76, 01-Aug-26
]
TIME_PATTERN = r"\b\d{1,2}:\d{2}\s?(?:am|pm|AM|PM)\b"
PHONE_PATTERN = r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"
SSN_PATTERN = r"\b\d{3}-\d{2}-\d{4}\b"
EMAIL_PATTERN = r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"
LONG_DIGIT_PATTERN = r"\b\d[\d\-]{4,}\d\b"
# Alphanumeric ID/specimen codes: 6+ chars, all caps/digits, at least one digit
ALNUM_ID_PATTERN = r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{5,}\b"
ADDRESS_PATTERN = r"\b\d{1,6}\s+([A-Za-z0-9'.]+\s){1,5}(St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane|Way|Ct|Court|Pl|Place|Suite|Ste)\b\.?"
ALLCAPS_NAME_PATTERN = r"\b[A-Z][A-Z'\-]+,\s*[A-Z][A-Z'\-]+\b"
# A single ALLCAPS word alone on its own line -- catches "LAST"/"FIRST"
# printed on separate lines with no comma (e.g. Genova SIBO report), and is
# deliberately broad since over-masking a stray label is a safe trade here.
STANDALONE_ALLCAPS_LINE_PATTERN = r"^[A-Z][A-Z'\-]{1,19}$"
LABELED_NAME_PATTERN = r"(?:Patient(?:\s+Name)?|Name|Prepared for|Member|Client)\s*:?\s*\n?\s*([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,2})"


def shape(s):
    """Replace every letter/digit with a placeholder character that preserves
    case and digit-ness but destroys the actual value. Punctuation/spacing
    untouched."""
    out = []
    for c in s:
        if c.isdigit():
            out.append("9")
        elif c.isupper():
            out.append("X")
        elif c.islower():
            out.append("x")
        else:
            out.append(c)
    return "".join(out)


def tag(label):
    def _sub(m):
        return f"[{label}:{shape(m.group(0))}]"
    return _sub


def tag_group1(label):
    def _sub(m):
        return m.group(0).replace(m.group(1), f"[{label}:{shape(m.group(1))}]")
    return _sub


def mask_text(text, known_values):
    masked = text

    # Standalone ALLCAPS name lines first, before anything else touches them.
    masked = re.sub(STANDALONE_ALLCAPS_LINE_PATTERN, tag("NAME?"), masked, flags=re.MULTILINE)

    for term in sorted(known_values, key=len, reverse=True):
        if not term.strip():
            continue
        masked = re.sub(re.escape(term), lambda m: f"[KNOWN:{shape(m.group(0))}]", masked, flags=re.IGNORECASE)

    for pat in DATE_PATTERNS:
        masked = re.sub(pat, tag("DATE"), masked)

    masked = re.sub(TIME_PATTERN, tag("TIME"), masked)
    masked = re.sub(EMAIL_PATTERN, tag("EMAIL"), masked)
    masked = re.sub(SSN_PATTERN, tag("SSN"), masked)
    masked = re.sub(PHONE_PATTERN, tag("PHONE"), masked)
    masked = re.sub(ADDRESS_PATTERN, tag("ADDRESS"), masked)
    masked = re.sub(ALLCAPS_NAME_PATTERN, tag("NAME?"), masked)
    masked = re.sub(LABELED_NAME_PATTERN, tag_group1("NAME?"), masked, flags=re.IGNORECASE)
    masked = re.sub(ALNUM_ID_PATTERN, tag("ID#"), masked)
    masked = re.sub(LONG_DIGIT_PATTERN, tag("ID#"), masked)

    return masked


def process(pdf_path: Path, known_values):
    doc = fitz.open(str(pdf_path))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{pdf_path.stem}.txt"

    lines = [f"# Structure review for: {pdf_path.name}", f"# Pages: {len(doc)}", ""]
    for i, page in enumerate(doc):
        lines.append(f"===== PAGE {i + 1} =====")
        raw = page.get_text()
        lines.append(mask_text(raw, known_values))
        lines.append("")

    doc.close()
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"-> Wrote {out_path}")
    print("   OPEN AND REVIEW THIS FILE before sharing it — confirm every placeholder looks like scrambled X/x/9 text, not a real readable value.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+", help="PDF files to extract structure from")
    parser.add_argument("--known", default="", help="Comma-separated list of real values you already know appear in the file (e.g. patient name) to force-mask")
    args = parser.parse_args()

    known_values = [v.strip() for v in args.known.split(",") if v.strip()]
    extra = []
    for v in known_values:
        extra.extend([w for w in re.split(r"[^a-zA-Z]", v) if len(w) > 2])
    known_values.extend(extra)

    for p in args.pdfs:
        path = Path(p)
        if not path.exists():
            print(f"! Skipping {p} — not found")
            continue
        process(path, known_values)


if __name__ == "__main__":
    main()
