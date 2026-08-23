#!/usr/bin/env python3
"""
watch_and_deidentify.py

Runs continuously in the background (no window, no terminal, no port) and
watches two local folders:

1. "Incoming" -- drop a new lab report PDF here and it is automatically
   de-identified using the same logic as deidentify_labs.py, with the result
   dropped in "Deidentified - Ready to Upload". You still upload that file to
   Claude yourself, and still keep the crosswalk CSV local, exactly as before.

2. "Treatment Plans - Incoming" -- once Claude has generated the treatment
   plan from the de-identified report, save that Word document here. It is
   automatically re-identified (patient name/DOB restored from the local
   crosswalk CSV, using the same logic as reidentify_word.py) and the result
   is dropped in "Treatment Plans - Patient Ready".

Both automations only run the same deterministic, already-tested logic that
used to require dragging a file into a web UI -- nothing about the matching
or replacement rules changed, just how the step gets triggered. Always open
the final document once and confirm the patient name/DOB are correct before
sending or filing it.

FOLDER LAYOUT (created automatically next to this script on first run):
    Incoming/                          <- drop new report PDFs here
    Deidentified - Ready to Upload/    <- safe files land here; upload to Claude
    Originals - Do Not Upload/         <- original PDFs are moved here after processing
    Treatment Plans - Incoming/        <- drop the Word doc Claude generated here
    Treatment Plans - Patient Ready/   <- reidentified Word docs land here
    Treatment Plans - Archive/         <- the de-identified-named Word doc is moved
                                           here after a successful re-identify
    Needs Review/                      <- anything the script could NOT confidently
                                           process lands here untouched, with a
                                           .reason.txt explaining why; DO NOT upload
                                           or send anything from this folder
    watcher.log                        <- activity log for troubleshooting
    *_crosswalk.csv                    <- written to the app root, same place the
                                           original Re-identify tab always looked

USAGE
-----
    python watch_and_deidentify.py            # run continuously (Ctrl+C to stop)
    python watch_and_deidentify.py --once      # process whatever's waiting, then exit (for testing)

For unattended background use, install this as a background service instead of
running it directly:
    Windows -> install_watcher_task.ps1   (Task Scheduler, starts at logon)
    macOS   -> install_watcher_launchagent.sh   (LaunchAgent, starts at login)
This script itself is identical on both platforms -- only the install
mechanism and the notification method (win11toast vs. osascript) differ.
"""

import sys
import os

# pythonw.exe (no console window) leaves sys.stdout/stderr as None. Any print()
# call anywhere -- including inside the imported deidentify_labs functions --
# would crash the whole watcher. Give them somewhere harmless to write instead.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import io
import csv
import time
import shutil
import logging
import zipfile
import argparse
import datetime
import contextlib
import subprocess
from pathlib import Path

import fitz  # PyMuPDF

from deidentify_labs import (
    process_pdf_doc,
    format_case_code_for_filename,
    clean_filename_fully,
    make_filename_safe,
    patient_name_from_identifiers,
)
from report_templates import TEMPLATES
from reidentify_word import (
    reidentify_docx_file,
    find_leftover_placeholders,
    detect_case_code_from_docx,
    load_crosswalk,
    parse_crosswalk_mappings,
)

APP_ROOT = Path(__file__).parent.resolve()
INCOMING_DIR = APP_ROOT / "Incoming"
READY_DIR = APP_ROOT / "Deidentified - Ready to Upload"
ARCHIVE_DIR = APP_ROOT / "Originals - Do Not Upload"
TREATMENT_PLAN_INCOMING_DIR = APP_ROOT / "Treatment Plans - Incoming"
TREATMENT_PLAN_READY_DIR = APP_ROOT / "Treatment Plans - Patient Ready"
TREATMENT_PLAN_ARCHIVE_DIR = APP_ROOT / "Treatment Plans - Archive"
NEEDS_REVIEW_DIR = APP_ROOT / "Needs Review"
LOG_PATH = APP_ROOT / "watcher.log"

POLL_INTERVAL_SECONDS = 3
STABLE_CHECK_DELAY_SECONDS = 1.5
IGNORE_PREFIXES = ("~$", ".", "_temp")
IGNORE_SUFFIXES = (".tmp", ".crdownload", ".part")

log = logging.getLogger("watcher")


def setup_logging():
    log.setLevel(logging.INFO)
    handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(handler)


def ensure_folders():
    for d in (
        INCOMING_DIR, READY_DIR, ARCHIVE_DIR,
        TREATMENT_PLAN_INCOMING_DIR, TREATMENT_PLAN_READY_DIR, TREATMENT_PLAN_ARCHIVE_DIR,
        NEEDS_REVIEW_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def notify(title, message):
    """Best-effort desktop notification (Windows toast or macOS notification
    center). Never allowed to crash the watcher -- this is a nice-to-have."""
    try:
        if sys.platform == "darwin":
            # osascript ships with every Mac -- no extra dependency needed.
            escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
            escaped_message = message.replace("\\", "\\\\").replace('"', '\\"')
            script = f'display notification "{escaped_message}" with title "{escaped_title}"'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        elif sys.platform == "win32":
            from win11toast import toast
            toast(title, message)
        else:
            log.info("Notification skipped (unsupported platform %s): %s - %s", sys.platform, title, message)
    except Exception:
        log.info("Notification skipped (notifier unavailable): %s - %s", title, message)


def is_ignorable(path: Path, expected_suffix: str) -> bool:
    name_lower = path.name.lower()
    if name_lower.startswith(IGNORE_PREFIXES):
        return True
    if name_lower.endswith(IGNORE_SUFFIXES):
        return True
    if path.suffix.lower() != expected_suffix:
        return True
    return False


def is_file_stable(path: Path) -> bool:
    """Returns True once a file's size has stopped changing and it's not locked
    for writing by whatever process saved it (browser download, Word, etc.)."""
    try:
        size_before = path.stat().st_size
    except FileNotFoundError:
        return False

    time.sleep(STABLE_CHECK_DELAY_SECONDS)

    try:
        size_after = path.stat().st_size
    except FileNotFoundError:
        return False

    if size_before != size_after or size_after == 0:
        return False

    try:
        with open(path, "rb"):
            pass
    except PermissionError:
        return False

    return True


def unique_destination(directory: Path, filename: str) -> Path:
    """Avoids overwriting an existing file of the same name in the destination folder."""
    dest = directory / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def generate_case_code() -> str:
    return datetime.datetime.now().strftime("CASE-%Y-%m-%d %H:%M:%S")


def extract_docx_all_xml_text(docx_path: Path) -> str:
    """Concatenates every XML part of a docx (body, headers, footers) so a
    substring check reflects the whole visible document, not just document.xml."""
    parts = []
    try:
        with zipfile.ZipFile(docx_path) as z:
            for name in z.namelist():
                if name.endswith(".xml"):
                    parts.append(z.read(name).decode("utf-8", errors="ignore"))
    except Exception:
        pass
    return "\n".join(parts)


def call_capturing_output(fn, *args, **kwargs):
    """Runs fn and captures anything it printed, so the reason behind a
    Needs Review outcome (which the imported functions only ever print,
    never raise) doesn't get lost when there's no console to see it."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue().strip()


def append_crosswalk(case_code: str, crosswalk_rows: list):
    if not crosswalk_rows:
        return
    safe_case_code = make_filename_safe(case_code)
    crosswalk_path = APP_ROOT / f"{safe_case_code}_crosswalk.csv"
    file_exists = crosswalk_path.exists()
    with open(crosswalk_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "source_file", "case_code", "field", "original_value", "occurrences_redacted"
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerows(crosswalk_rows)


def process_one_file(path: Path):
    log.info("Processing new file: %s", path.name)
    case_code = generate_case_code()
    crosswalk_rows = []

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        log.error("Could not open %s as a PDF: %s", path.name, e)
        move_to_needs_review(path, reason=f"Could not open as PDF: {e}")
        return

    try:
        identifiers, total_redactions = process_pdf_doc(doc, path.name, case_code, crosswalk_rows)
    except Exception as e:
        doc.close()
        log.error("Redaction failed for %s: %s", path.name, e)
        move_to_needs_review(path, reason=f"Redaction error: {e}")
        return

    if not identifiers:
        doc.close()
        log.warning("No known identifier fields matched in %s — routing to Needs Review.", path.name)
        move_to_needs_review(
            path,
            reason="No known identifier fields (name/DOB/IDs) were found. "
                   "The report template may have changed, or this isn't a "
                   f"supported lab report ({', '.join(t.NAME for t in TEMPLATES)}). "
                   "DO NOT upload this file anywhere."
        )
        notify(
            "De-identification needs review",
            f"{path.name} could not be confidently de-identified. "
            f"Check the Needs Review folder — do not upload it as-is."
        )
        return

    patient_name = patient_name_from_identifiers(identifiers)
    safe_case = format_case_code_for_filename(case_code)
    cleaned_filename = clean_filename_fully(path.name, patient_name, APP_ROOT)
    out_filename = f"{safe_case}-{Path(cleaned_filename).stem}_deidentified.pdf"
    out_path = unique_destination(READY_DIR, out_filename)

    try:
        doc.save(str(out_path))
    finally:
        doc.close()

    append_crosswalk(case_code, crosswalk_rows)

    archive_path = unique_destination(ARCHIVE_DIR, path.name)
    shutil.move(str(path), str(archive_path))

    fields_found = ", ".join(sorted(identifiers.keys()))
    log.info(
        "De-identified %s -> %s (case %s; %d redactions; fields: %s)",
        path.name, out_path.name, case_code, total_redactions, fields_found
    )
    notify(
        "Ready to upload",
        f"{out_path.name} is de-identified and ready — "
        f"please skim it once before uploading to Claude."
    )


def process_one_treatment_plan(path: Path):
    log.info("Processing new treatment plan: %s", path.name)

    case_code = detect_case_code_from_docx(path)
    if not case_code:
        log.warning("Could not detect a Case ID in %s — routing to Needs Review.", path.name)
        move_to_needs_review(
            path,
            reason="Could not detect a Case ID in the filename or document text. "
                   "The document may be missing the [CASE-...] placeholder."
        )
        notify(
            "Re-identification needs review",
            f"{path.name} — no Case ID found. Check the Needs Review folder."
        )
        return

    mappings = load_crosswalk(case_code, APP_ROOT)
    if not mappings:
        log.warning("No crosswalk found for Case ID '%s' (%s) — routing to Needs Review.", case_code, path.name)
        move_to_needs_review(
            path,
            reason=f"Detected Case ID '{case_code}' but no matching *_crosswalk.csv "
                   f"was found in the app folder. Has it been moved, renamed, or deleted?"
        )
        notify(
            "Re-identification needs review",
            f"{path.name} — Case ID '{case_code}' has no matching crosswalk. Check Needs Review."
        )
        return

    stem = path.stem
    if stem.endswith("_deidentified"):
        stem = stem[:-len("_deidentified")]
    elif stem.endswith("-deidentified"):
        stem = stem[:-len("-deidentified")]
    out_filename = f"{stem}_reidentified.docx"
    out_path = unique_destination(TREATMENT_PLAN_READY_DIR, out_filename)

    replaced, output_log = call_capturing_output(reidentify_docx_file, path, case_code, mappings, out_path)

    if not replaced:
        if out_path.exists():
            out_path.unlink()
        log.warning(
            "Re-identification produced no usable result for %s (case %s): %s",
            path.name, case_code, output_log
        )
        move_to_needs_review(
            path,
            reason=f"Case ID '{case_code}' and its crosswalk were found, but re-identification "
                   f"did not produce a usable document (0 placeholders replaced, or an error). "
                   f"Details:\n{output_log}"
        )
        notify(
            "Re-identification needs review",
            f"{path.name} — nothing was replaced. Check the Needs Review folder."
        )
        return

    # A non-zero replacement count only proves SOMETHING matched -- it doesn't
    # prove the name specifically made it into the output (an unrecognized
    # name convention could otherwise fail silently, leaving a
    # half-reidentified document that still looks "done"). Verify the
    # expected value landed before treating this as safe to hand over.
    info = parse_crosswalk_mappings(mappings)
    output_text = extract_docx_all_xml_text(out_path)
    problems = []
    if info.get("name") and info["name"] not in output_text:
        problems.append(f"patient name ('{info['name']}')")

    # A field landing somewhere in the output (checked above) doesn't prove
    # THIS document's placeholder for that field was the one that matched --
    # a real-name match elsewhere (e.g. the footer's literal case code) can
    # mask an untouched placeholder elsewhere in the body. Independently
    # scan for any known placeholder string still present at all; these
    # pattern names are generic labels, never patient data, so it's always
    # safe to log/write them (unlike the name value above).
    leftover = find_leftover_placeholders(output_text)
    if leftover:
        problems.append(f"leftover placeholder text still present ({', '.join(sorted(set(leftover)))})")

    # Name is only ever restored via the literal case-code reference (see
    # reidentify_word.py) -- if that literal string is still sitting in the
    # output, the document never referenced it for the name, and no amount
    # of guessing will fix it. Not PII: the case code is an identifier we
    # chose, never patient data. DOB is intentionally not checked here --
    # this pipeline no longer restores DOB at all (2026-08-23); the
    # treatment plan is expected to carry only an approximate age instead.
    if case_code in output_text or f"[{case_code}]" in output_text:
        problems.append("the literal case code is still present in the output — the document "
                         "never referenced it for the patient's name")

    if problems:
        if out_path.exists():
            out_path.unlink()
        problem_desc = " and ".join(problems)
        log.warning(
            "Re-identification of %s (case %s) looked successful (%d placeholders replaced) "
            "but %s — routing to Needs Review.",
            path.name, case_code, replaced, problem_desc
        )
        move_to_needs_review(
            path,
            reason=f"Case ID '{case_code}' matched and {replaced} placeholder(s) were replaced, "
                   f"but {problem_desc}. The placeholder text in this document likely doesn't "
                   f"match any pattern this script knows about — check the document for what "
                   f"placeholder was actually used and add it to reidentify_word.py.\n\n"
                   f"Details:\n{output_log}"
        )
        notify(
            "Re-identification needs review",
            f"{path.name} — {problem_desc}. Check Needs Review."
        )
        return

    archive_path = unique_destination(TREATMENT_PLAN_ARCHIVE_DIR, path.name)
    shutil.move(str(path), str(archive_path))

    log.info(
        "Re-identified %s -> %s (case %s; %d placeholders replaced)",
        path.name, out_path.name, case_code, replaced
    )
    notify(
        "Ready to send",
        f"{out_path.name} is re-identified — please confirm the patient name/DOB "
        f"match before sending or filing it."
    )


def move_to_needs_review(path: Path, reason: str):
    try:
        dest = unique_destination(NEEDS_REVIEW_DIR, path.name)
        shutil.move(str(path), str(dest))
        note_path = dest.with_suffix(dest.suffix + ".reason.txt")
        note_path.write_text(reason, encoding="utf-8")
        log.info("Moved %s to Needs Review: %s", path.name, reason)
    except Exception as e:
        log.error("Failed to move %s to Needs Review: %s", path.name, e)


def scan_once():
    try:
        candidates = [p for p in INCOMING_DIR.iterdir() if p.is_file() and not is_ignorable(p, ".pdf")]
    except FileNotFoundError:
        return

    for path in candidates:
        if not path.exists():
            continue  # could have been picked up and moved already
        if not is_file_stable(path):
            continue
        try:
            process_one_file(path)
        except Exception:
            log.exception("Unexpected error while processing %s", path.name)
            move_to_needs_review(path, reason="Unexpected error during processing — see watcher.log")


def scan_treatment_plans_once():
    try:
        candidates = [
            p for p in TREATMENT_PLAN_INCOMING_DIR.iterdir()
            if p.is_file() and not is_ignorable(p, ".docx")
        ]
    except FileNotFoundError:
        return

    for path in candidates:
        if not path.exists():
            continue  # could have been picked up and moved already
        if not is_file_stable(path):
            continue
        try:
            process_one_treatment_plan(path)
        except Exception:
            log.exception("Unexpected error while processing %s", path.name)
            move_to_needs_review(path, reason="Unexpected error during processing — see watcher.log")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true",
        help="Process whatever is currently in Incoming/ once, then exit (useful for testing)."
    )
    args = parser.parse_args()

    ensure_folders()
    setup_logging()
    log.info("Watcher starting. Watching: %s and %s", INCOMING_DIR, TREATMENT_PLAN_INCOMING_DIR)

    if args.once:
        scan_once()
        scan_treatment_plans_once()
        log.info("Single pass complete.")
        return

    try:
        while True:
            scan_once()
            scan_treatment_plans_once()
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log.info("Watcher stopped (KeyboardInterrupt).")


if __name__ == "__main__":
    main()
