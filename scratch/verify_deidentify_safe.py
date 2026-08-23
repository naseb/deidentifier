#!/usr/bin/env python3
"""
verify_deidentify_safe.py

PII-safe verification harness for the report_templates registry.

Per CLAUDE.md's guardrail: deidentify_labs.py's process_pdf_doc() prints
"label: value" for every identifier it finds, which is fine when the USER
runs it (they already know their own patients' PII) but must never be run
directly by the assistant, because that prints real PII straight into the
assistant's context.

This script performs the same detect -> extract -> redact -> verify pipeline
but NEVER prints an identifier value, a source filename, or anything else
that could contain PII. It only prints:
  - which template matched (a template name, not patient data)
  - field labels found (labels like "patient_name", not values)
  - a redaction count per field
  - a boolean: did the original value still appear anywhere in the
    redacted output? (computed internally; only the boolean is printed)

Run this directly against Lab-templates/*.pdf. Samples are referred to only
as "sample_1", "sample_2", ... in all output -- never by filename, since one
of the real filenames in this repo contains a patient name.

Deidentified output PDFs are written to scratch/test_output/ for the USER
to visually confirm (per CLAUDE.md next-step #2). This script's own stdout
is safe for the assistant to read.
"""

import sys
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from report_templates import find_identifiers_for_doc  # noqa: E402
from deidentify_labs import redact_value  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "Lab-templates"
OUT_DIR = Path(__file__).resolve().parent / "test_output"


def value_survives(doc, value):
    """True if `value` is still findable anywhere in doc. Boolean only --
    the value itself is never printed by the caller."""
    if not value:
        return False
    for page in doc:
        if page.search_for(value):
            return True
        if value in page.get_text():
            return True
    return False


def replacement_text_visible(doc, replacement):
    """True if `replacement` (a generic case-code label, never PII -- safe
    to inspect directly) renders in a non-black color. Catches the
    black-fill/black-text invisible-redaction bug found 2026-08-23: text
    can be technically present and extractable while being visually
    invisible against the black redaction box."""
    if not replacement:
        return True
    for page in doc:
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if replacement in span.get("text", ""):
                        if span.get("color", 0) == 0:
                            return False
    return True


def main():
    OUT_DIR.mkdir(exist_ok=True)
    pdf_paths = sorted(SAMPLES_DIR.glob("*.pdf"))

    if not pdf_paths:
        print(f"No PDFs found in {SAMPLES_DIR}")
        return

    case_code = sys.argv[1] if len(sys.argv) > 1 else "TEST-CASE"
    print(f"Verifying {len(pdf_paths)} sample PDF(s) under case code '{case_code}' "
          f"-- values never printed below.\n")

    overall_pass = True

    for i, path in enumerate(pdf_paths, start=1):
        label = f"sample_{i}"
        doc = fitz.open(str(path))

        identifiers, replacement_map, template_name = find_identifiers_for_doc(doc)

        if not identifiers:
            print(f"[{label}] ! No template matched -- unmatched file, would be routed to manual review.")
            doc.close()
            overall_pass = False
            continue

        print(f"[{label}] template matched: {template_name}")
        print(f"[{label}] fields found ({len(identifiers)}): {', '.join(sorted(identifiers.keys()))}")

        total_redactions = 0
        field_results = []
        for field_label, value in identifiers.items():
            replacement_template = replacement_map.get(field_label, "[REDACTED]")
            replacement = replacement_template.format(case_code=case_code)
            n = redact_value(doc, value, replacement)
            total_redactions += n
            leaked = value_survives(doc, value)
            visible = replacement_text_visible(doc, replacement)
            field_results.append((field_label, n, leaked, visible))
            if leaked or not visible:
                overall_pass = False

        print(f"[{label}] total redactions applied: {total_redactions}")
        for field_label, n, leaked, visible in field_results:
            leak_status = "LEAKED (FAIL)" if leaked else "clean"
            vis_status = "visible" if visible else "INVISIBLE TEXT (FAIL)"
            print(f"[{label}]   - {field_label}: {n} occurrence(s) redacted, "
                  f"leak-check: {leak_status}, replacement-visibility: {vis_status}")

        out_path = OUT_DIR / f"{label}_deidentified.pdf"
        doc.save(str(out_path))
        doc.close()
        print(f"[{label}] -> wrote {out_path.name} for visual review\n")

    print("=" * 60)
    if overall_pass:
        print("PASS: every matched template's identifiers were fully redacted")
        print("(no original value was found in its own output).")
    else:
        print("FAIL: see LEAKED lines / unmatched files above.")
    print("\nThis is an automated text-search check only. Per CLAUDE.md next")
    print(f"steps, the user should still open the PDFs in {OUT_DIR}")
    print("and visually confirm no identifying text remains before trusting")
    print("any of these templates as production-ready.")


if __name__ == "__main__":
    main()
