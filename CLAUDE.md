# Lab-deidentifier

Local tool that redacts patient PII from lab report PDFs before any content
is uploaded to Claude for treatment-plan drafting. Originally built for
Optimal DX reports only; being generalized to support multiple lab
companies via a plugin-style template registry.

## CRITICAL GUARDRAIL — read before running anything against real PDFs

**Never run a script or command whose output could print a real PII value
into the assistant's context.** This project's whole premise is that PII
never reaches an LLM. On 2026-08-22, running `deidentify_labs.py` directly
(via Bash) against 3 real sample PDFs printed real patient names, DOBs,
phone numbers, and ID numbers straight into the assistant's context, because
`process_pdf_doc()` logs `label: value` (not just the label) for each field
it finds. That defeated the entire point of the tool.

Going forward:
- Before the assistant runs any script over a real lab PDF, check what it
  prints. If it echoes matched **values** (not just labels/counts), the
  assistant must not run it directly.
- Prefer: the user runs it and reports back pass/fail + counts, OR the
  assistant writes/uses a harness that only surfaces safe metadata (e.g.
  `"6 fields found, 112 redactions, template=quest"`) with values stripped.
- For reviewing a NEW report format's structure (before a template exists
  for it), use `scratch/extract_template_structure.py` — it produces a
  shape-preserving masked view (letters → X/x, digits → 9, punctuation kept)
  that the **user reviews and confirms clean** before sharing with the
  assistant. Never have the assistant read a raw sample PDF directly.

## Architecture

- `deidentify_labs.py` — core redaction engine. `process_pdf_doc()` calls
  `report_templates.find_identifiers_for_doc(doc)`, which tries each
  registered template's `detect()` in order and runs the first match's
  `extract()`. If nothing matches, the file is left alone (no guessing) and
  should be routed to manual review.
- `report_templates/` — one module per lab report format:
  - `optimal_dx.py` — Optimal DX Functional Health Report
  - `quest.py` — Quest Diagnostics
  - `genova_oap_nutripath.py` — NutriPATH-branded Genova Organic Acids Profile
  - `genova_sibo.py` — Genova Diagnostics SIBO breath test
  - `_shared_ids.py` — labeled ID/phone patterns shared by optimal_dx + quest
  - `__init__.py` — the `TEMPLATES` registry + dispatch function

  **To add a new lab company:** create a new module with `NAME`,
  `REPLACEMENT_MAP`, `detect(doc, full_text, page1_text)`, and
  `extract(doc, full_text, page1_text)`, then add it to the `TEMPLATES` list
  in `__init__.py`. Keep detection specific (a distinctive brand string or
  label combination) so it can't accidentally fire on another lab's report.
- `watch_and_deidentify.py` — background folder-watcher wrapping the same
  `process_pdf_doc()` logic; imports `patient_name_from_identifiers()` from
  `deidentify_labs.py` for filename cleanup (handles both single-field and
  split first/last-name templates).
- `reidentify_word.py` — restores the real patient NAME (only) into a
  Claude-drafted treatment plan DOCX using the local crosswalk CSV.
  **Contract placeholder must follow:** the ONLY name placeholder this
  script recognizes is the literal case-code reference every
  `report_templates/*.py` REPLACEMENT_MAP writes in place of the name —
  e.g. `[CASE-2026-08-21-08-54-26]` (brackets or bare). A treatment plan
  must reference the patient using that literal string wherever it needs
  the name, including in narrative body text — not a paraphrase like "the
  patient," "De-Identified Patient," or "Jane Doe". This is enforced on
  the drafting side (prompting instructions for whatever generates the
  treatment plan docx), not in this repo.
  **DOB is deliberately NOT restored at all** (as of 2026-08-23, see Status
  item 9) — the drafting instructions have Claude write an approximate age
  ("Age 64") instead of reconstructing a real date of birth, after DOB
  proved to be a recurring source of fragility (vendor date-format regexes
  that don't always match, and a same-day marker-collision bug). This
  script does NOT guess at freeform name phrasings either (it used to, see
  Status item 6).
  `watch_and_deidentify.py`'s post-replacement check
  (`find_leftover_placeholders` + a literal-case-code-still-present check)
  routes a document to Needs Review, rather than reporting false success,
  if the name marker was never replaced.
- `Lab-templates/` — holds **real, unredacted sample PDFs** used to design
  new templates. Treat as sensitive; this is not a code folder despite the
  similar name to `report_templates/`.
- `scratch/extract_template_structure.py` — the safe structure-review tool
  described in the guardrail section above.

## Status as of 2026-08-22

**Done:**
- Copied/renamed project from `deidentify-optimal-dx-V4` to
  `Lab-deidentifier` (paths are all `Path(__file__)`-relative, so this was
  safe).
- Built the `report_templates/` plugin registry, replacing the old
  single-function `find_identifiers()`.
- Wrote 2 new templates (`genova_oap_nutripath`, `genova_sibo`) from
  shape-masked structural review of 3 real sample PDFs in `Lab-templates/`
  (patient reviewed and confirmed the masked review files were clean before
  sharing).
- Verified `page.search_for()` is case-insensitive (small synthetic test),
  which matters for `genova_sibo` since the patient name appears ALLCAPS on
  page 1 but may render differently elsewhere.
- Ran all 4 templates against their real sample PDFs — correct template
  detected in each case, plausible field counts and redaction counts. The
  code path is believed correct, but **this specific verification run is
  the one that violated the guardrail above** (raw values were printed to
  the assistant) — treat the templates as functionally promising but not
  yet independently re-verified in a PII-safe way.

**Known judgment calls made (flagged for user confirmation, not yet
explicitly confirmed):**
- Practitioner/ordering-clinician names (e.g. "Danielle Nasello, NPC") are
  intentionally **not** redacted — only patient identifiers are in scope,
  consistent with the original Optimal DX/Quest design. Confirmed correct
  for the NutriPATH sample; assumed to generalize.
- Genova SIBO's `Route Number:` (internal order routing) and NutriPATH's
  `Test Codes:` are treated as administrative/non-patient-identifying and
  left un-redacted — same category as lab-internal codes elsewhere in the
  existing templates.
- Added a new `Lab Ref #:` field to the `quest` template (redacted) — not
  present in the original single-template code, seen on the newer Quest
  sample.

**Still pending / next steps:**
1. ~~Re-verify the 4 templates without exposing raw PII~~ — DONE 2026-08-22.
   Built `scratch/verify_deidentify_safe.py`: runs detect/extract/redact for
   every PDF in `Lab-templates/` and only ever prints template name, field
   *labels*, redaction counts, and a leaked/clean boolean per field (checked
   by searching the redacted output for the original value internally —
   the value itself is never printed). Samples are referred to as
   `sample_1`/`sample_2`/`sample_3`/..., never by filename, since real
   filenames in `Lab-templates/` can contain a patient name. The assistant
   ran this directly (safe to do, unlike `deidentify_labs.py`) and got PASS
   for all samples: `genova_oap_nutripath` (7 fields, 112 redactions),
   `quest` (8 fields, 45 redactions), `genova_sibo` (5 fields, 11
   redactions) — no original value survived in its own output. User visually
   confirmed samples 1-3 clean on 2026-08-22.
   User then added a 4th sample (`optimal_dx`) to `Lab-templates/` — re-ran
   the harness same day, `optimal_dx` matched correctly, 2 fields
   (`patient_name_titlecase`, `dob_long`), 72 redactions, clean. Awaiting
   user's visual confirmation of this one (now `sample_2_deidentified.pdf`,
   indices reshuffled alphabetically by the new filename).
2. Have the user personally open the output PDFs in `scratch/test_output/`
   (the `sample_N_deidentified.pdf` files from the safe harness above, and
   the older `TEST-CASE-*_deidentified.pdf` files from the original
   exposure-causing run) and confirm no identifying text remains, before
   treating any of these templates as production-ready. Automated text
   search is not a substitute for visual/human confirmation (e.g. it
   wouldn't catch PII rendered as an image rather than text). All 4
   templates now have at least one sample verified by the safe harness; only
   optimal_dx's sample still needs the user's visual sign-off.
3. ~~Migrate the background watcher~~ — DONE 2026-08-22. The old Windows
   Scheduled Task ("OptimalDX Deidentify Watcher") was pointed at the **old**
   `deidentify-optimal-dx-V4` folder; user ran (elevated)
   `uninstall_watcher_task.ps1` from the old folder then
   `install_watcher_task.ps1` from here. Verified: the live task's Action now
   points at `C:\Users\bnase\Lab-deidentifier\watch_and_deidentify.py` with
   working directory `Lab-deidentifier`. Old folder's `Incoming`/`Needs
   Review` were empty at migration time, so nothing was stranded there.
   Also rebranded the tool's self-identity from "OptimalDX" to
   "Lab-deidentifier" per user request 2026-08-22: scheduled task renamed to
   `Lab Deidentifier Watcher` (in `install_watcher_task.ps1` /
   `uninstall_watcher_task.ps1` — also fixed `uninstall_watcher_task.ps1` to
   actually report failure on access-denied instead of always printing
   "Removed..."), macOS LaunchAgent label renamed to
   `com.labdeidentifier.watcher` (in `install_watcher_launchagent.sh` /
   `uninstall_watcher_launchagent.sh`, currently unused on this Windows
   machine), and the watcher's "unmatched file" log message in
   `watch_and_deidentify.py` now lists supported templates dynamically from
   `report_templates.TEMPLATES` instead of a hardcoded stale "OptimalDX/Quest"
   string. Deliberately NOT renamed: `report_templates/optimal_dx.py` and its
   `NAME = "optimal_dx"` — that module correctly names the actual Optimal DX
   lab report format it detects, same as `quest.py`/`genova_*.py` name their
   labs.
   **Action still needed from the user:** the *already-registered* scheduled
   task is still named "OptimalDX Deidentify Watcher" (renaming the script
   doesn't rename a task already installed under the old name) — re-run
   (elevated) `uninstall_watcher_task.ps1` then `install_watcher_task.ps1`
   once more to pick up the new "Lab Deidentifier Watcher" name.
4a. **Bug found & partially fixed 2026-08-22 — re-identification false-positive.**
   A real treatment plan (case `CASE-2026-08-21-08-54-26`) came out of the
   watcher logged as a success ("1 placeholders replaced") but still showed
   the literal placeholder text in the body when opened. Diagnosed PII-safely
   with `scratch/diagnose_reidentify_safe.py <CASE-CODE>` (prints only
   booleans/counts/XML-part-names, never values — reusable for future
   incidents like this). Root cause: the document's patient-identity table
   cell held bare `"De-identified"` (no "Patient"), which
   `reidentify_word.py` only maps to **DOB**, not name — and this case's
   crosswalk had no DOB (the DOB regex didn't match this PDF's date format),
   so nothing filled it in. The old post-check only verified the real name
   appeared *somewhere* in the output, and passed because the name
   coincidentally landed in the footer via an unrelated case-code
   substitution, masking the untouched body placeholder.
   Fix applied (user-approved, scoped to this only): added
   `find_leftover_placeholders()` to `reidentify_word.py` and wired it into
   `watch_and_deidentify.py`'s post-replacement check — if ANY known
   placeholder string is still present anywhere in the output after
   replacement, it's now routed to Needs Review instead of shipped as
   "success", regardless of which specific placeholder text triggered it.
   Verified the new check does flag this exact case's leftover text.
   User chose to leave the bad output file in `Treatment Plans - Patient
   Ready` and handle it manually rather than have it auto-moved.
   **Not fixed / flagged but out of approved scope:**
   - `move_to_needs_review()` logs its full `reason` string via `log.info`,
     and the pre-existing "missing name/DOB" reason text embeds the raw
     name/DOB value — meaning `watcher.log` can already contain real PII in
     plaintext for any case that hit that path. (The new leftover-placeholder
     reason text is safe — it only ever contains generic pattern labels like
     "De-identified", never patient data.) Needs a decision: strip values
     from the logged reason (keep them only in the `.reason.txt` file next to
     the moved document) or accept `watcher.log` as sensitive-adjacent.
   - This case's crosswalk has no `dob_long` — meaning the original Optimal
     DX PDF's DOB may never have been redacted before upload. Unverified:
     the original/deidentified PDFs for this specific case are no longer in
     `Originals - Do Not Upload` / `Deidentified - Ready to Upload` to check
     against.
4b. Decide what to do with `scratch/test_output/` — it contains a real
   crosswalk CSV and deidentified PDFs from local testing; fine to keep
   locally, but it's test clutter, not a real case.
5. More lab companies can be added the same way as templates 3 and 4 were:
   run `scratch/extract_template_structure.py` on a new sample, user
   reviews the masked output, then design `detect()`/`extract()` from that.
6. **Refactored 2026-08-23 — stopped guessing at name placeholders.** Item 4a's
   fail-safe caught the leftover-placeholder bug correctly, but the user
   judged the underlying design (13 guessed freeform phrasings for the name:
   "De-Identified Patient", "Jane Doe", case variants, etc.) as
   overcomplicated for something this repo can't control — the phrasing is
   invented by whatever drafts the treatment plan, not written by this
   pipeline. Refactored `reidentify_word.py` so patient NAME is restored
   ONLY via the literal case-code reference (see the new Architecture note
   on `reidentify_word.py` above); removed the freeform name-guessing
   entirely. DOB matching (freeform "De-Identified" family) is unchanged.
   The old freeform name phrasings are kept as a detection-only list so
   `find_leftover_placeholders` still flags one if it shows up (routes to
   Needs Review instead of silently failing); `watch_and_deidentify.py` also
   gained an explicit check for the literal case code still being present
   post-replacement. Verified with a synthetic (non-PII) test docx: the
   case-code reference gets replaced, a "De-Identified Patient" phrase
   elsewhere in the same doc is correctly left untouched and flagged as
   leftover.
   **User is separately updating the treatment-plan drafting prompt/
   instructions** (outside this repo) to always reference the patient via
   the literal `[CASE-...]` code rather than inventing phrasing — this
   refactor is the code-side half of that fix. `CASE-2026-08-21-08-54-26`
   (Needs Review) still needs its placeholder manually edited from bare
   "De-identified" to something using the case-code reference, or it will
   keep routing to Needs Review under the new rule too.
7. **Real bug found & fixed 2026-08-23 — redaction replacement text was
   invisible.** User noticed the sample deidentified PDFs show solid black
   boxes with NO visible placeholder text (screenshot: an "Hello Health"
   Optimal DX report, "Prepared for" field is just a black rectangle) —
   not `[CASE-...]` text as expected. This is very likely the actual root
   cause of the treatment-plan-drafting Claude inventing phrasing like
   "De-identified Patient" instead of using the case code (item 6): if that
   Claude reads the PDF visually/via vision, it would see nothing but a
   black box and have no way to know what literal text to use.
   Root cause, verified with a synthetic (non-PII) PDF: `redact_value()` in
   `deidentify_labs.py` called `page.add_redact_annot(inst, text=replacement,
   fill=(0, 0, 0))` — fill (the box) is black, and `text_color` was never
   set, which PyMuPDF defaults to black too. So the replacement text was
   real and extractable in the text layer (`get_text()` returns it fine),
   but rendered in black-on-black — invisible to a human or a vision model
   looking at the page, even though our automated leak-checks (which use
   `get_text()`) never would have caught this, since they only ever checked
   that the *original* value was gone, not that the *replacement* was
   legible.
   Fix: added `text_color=(1, 1, 1)` (white) to the `add_redact_annot` call
   in `redact_value()` (`deidentify_labs.py`). Verified with a synthetic
   PDF (rendered to PNG and visually confirmed white `[CASE-TEST-0001]`
   text is now clearly readable on the black box).
   Also fixed `scratch/verify_deidentify_safe.py`, which had its own
   **duplicated, stale copy** of `redact_value()` (missing the fix) instead
   of importing the real one from `deidentify_labs.py` — it was silently
   testing old behavior. Now imports `redact_value` directly, and gained a
   new `replacement_text_visible()` check (safe: only inspects the
   generic case-code replacement string, never PII) so this class of bug
   is caught automatically going forward. Re-ran against all 4 samples:
   every field now reports `replacement-visibility: visible`.
   **Action needed from the user:** this fix only affects PDFs de-identified
   *from now on*. Any already-deidentified PDF sitting in `Deidentified -
   Ready to Upload`, already uploaded to Claude, or already used to start a
   treatment-plan conversation was produced with the old invisible-text
   version — worth re-running `deidentify_labs.py` on the original report
   for any case still in flight, rather than assuming the existing
   deidentified copy is fixed.
8. **Bug found & fixed 2026-08-23 — name/DOB placeholder collision.** While
   manually testing with a case code standing in for the DOB field's value
   too (drafting Claude wrote `CASE-2026-08-21-08-54-26 | Age 64` as the
   DOB), the name-restoration rule matched the bare case code inside that
   DOB text and replaced it with the patient's name, producing "Lisa xyz |
   Age 64" — right idea, wrong field. Root cause: item 6's refactor made
   name matching a pure literal-string search with no concept of which
   field an occurrence sits in, so any stray case-code reference anywhere
   in the document — including one incorrectly placed in the DOB field —
   gets treated as a name placeholder. Compounding this, DOB restoration
   was still on the old freeform "De-Identified" guesswork (see item 6),
   itself unreliable, and `optimal_dx`'s DOB replacement text
   (`[DOB REDACTED — {case_code}]`) was the only template that even tied
   DOB to the case code at all — the other three templates wrote
   unqualified `[REDACTED]` with no case-code link whatsoever.
   Fix: gave DOB the same treatment as name got in item 6, but with a
   marker shaped to never collide with the name marker. Every
   `report_templates/*.py` REPLACEMENT_MAP now writes DOB as
   `[DOB-{case_code}]` (previously `[REDACTED]` for quest/genova_oap_nutripath/
   genova_sibo, `[DOB REDACTED — {case_code}]` for optimal_dx).
   `reidentify_word.py` now matches DOB only via that literal `DOB-<case
   code>` marker (bracketed or bare), replacing the freeform "De-Identified"
   *active* matching entirely (the freeform patterns are kept only in
   `DOB_PLACEHOLDER_PATTERNS` for `find_leftover_placeholders` detection,
   same treatment as the old name phrasings). Sort-by-length-descending in
   `reidentify_docx_file` (unchanged) guarantees the longer `[DOB-...]`/
   `DOB-...` targets get replaced before the shorter bare case-code target,
   so a correctly-marked DOB field can never be eaten by the name rule.
   `watch_and_deidentify.py` gained a matching "DOB marker still present"
   post-replacement check, mirroring the existing case-code one.
   Verified with two synthetic (non-PII) tests: (1) reproduced the exact
   reported collision — DOB field holding the bare case code instead of the
   new `DOB-` marker — confirming it still collides (expected: the marker
   only protects a document that actually uses it) and (2) confirmed a DOB
   field correctly holding `[DOB-{case_code}]` resolves to the real DOB
   with no cross-contamination of the name field.
   **This makes the prompting instructions even more important:** the
   drafting Claude must use TWO distinct markers now, never interchange
   them, and never reuse the name marker as a stand-in for "identifying
   info withheld" in the DOB field.
9. **Simplified 2026-08-23 — dropped DOB restoration entirely.** After
   reviewing several real Optimal DX reports, the user concluded lab report
   formats aren't consistent even within one vendor, and DOB in particular
   had already caused two rounds of fragility same-day (item 8's marker
   collision, plus vendor DOB regexes that don't always match a given
   report's date format). Decision: re-identification should only ever
   restore the patient NAME; DOB is left alone entirely. The
   treatment-plan drafting instructions now have Claude write an
   approximate age ("Age 64") instead of attempting to reconstruct a real
   DOB — removing the whole DOB-marker mechanism rather than continuing to
   patch it.
   Changes: reverted all 4 `report_templates/*.py` DOB replacement text
   back to plain `[REDACTED]` (dropping the `[DOB-{case_code}]` tie added
   in item 8 — no longer needed since nothing restores it).
   `reidentify_word.py`'s `reidentify_docx_file()` no longer builds any DOB
   replacement rules and no longer treats "no DOB in crosswalk" as
   blocking — only name is required. `DOB_PLACEHOLDER_PATTERNS` and the
   `find_leftover_placeholders`/`ALL_PLACEHOLDER_PATTERNS` machinery now
   cover name only. `watch_and_deidentify.py`'s post-replacement check
   dropped both the "DOB missing from output" and "DOB marker still
   present" checks accordingly — DOB is simply not part of the contract
   any more. `deidentify_labs.py` is UNCHANGED: it still redacts DOB out of
   the uploaded PDF exactly as before (that's a HIPAA/compliance step, not
   a restoration step, and stays regardless of whether DOB ever comes back
   for the treatment plan).
   Verified with a synthetic (non-PII) test: name restores correctly via
   the case-code marker, and a separate "Age: 64" string in the same
   document is left completely untouched (no DOB matching is attempted at
   all any more, so there's nothing left to collide with).
   The watcher was restarted after this change (as after every code edit
   to these files — Python doesn't hot-reload a long-running process, see
   the repeated "stale process" issue earlier the same day).
   **User is separately updating the treatment-plan drafting prompt** to
   tell Claude to use ONLY the `[CASE-...]` marker for the name and to
   just write an approximate age for DOB, never a marker or literal date.
10. **Bugs found & fixed 2026-08-23 — new Optimal DX report variant not
   detected.** User added a new real Optimal DX sample
   (`Lab-templates/MelissaSlater-OptimalDX-Practitioner-Aug-22-2026.pdf`)
   that landed in Needs Review with "No known identifier fields ... found".
   Diagnosed PII-safely using `scratch/extract_template_structure.py`
   (masked structural view) plus a couple of targeted boolean/shape-only
   checks (never printing actual values) once the user flagged that the
   masked review file itself had a leak. Two separate bugs found:
   - **The structure-review tool leaked a name.** User caught it visually:
     the masked file showed Melissa's real name in plain text right under
     "PREPARED FOR" on page 1. Root cause: `LABELED_NAME_PATTERN` in
     `scratch/extract_template_structure.py` matched "Prepared for" without
     `re.IGNORECASE`, so the ALL-CAPS "PREPARED FOR" label in this report
     didn't match and the name below it was never masked. Fix: added
     `flags=re.IGNORECASE` to that substitution. This is the safety tool
     itself, so this was a real (if contained — the user caught it before
     sharing anything with the assistant) failure of the guardrail process;
     the assistant never read the leaked file.
   - **The real bug**, same root cause but in production code:
     `report_templates/optimal_dx.py`'s `_NAME_PATTERN` had the identical
     case-sensitivity gap, which is why `detect()` failed on this report.
     Fixed with the same `re.IGNORECASE` treatment on both `_NAME_PATTERN`
     and `_DOB_PATTERN`. That alone wasn't sufficient, though: this report
     variant turned out to have **zero occurrences** of "DOB"/"birth"/"born"
     anywhere — it prints only an age ("49 year old female"), never a
     literal date of birth. Since `detect()` required both the name pattern
     AND the DOB pattern to match, it could never succeed on this variant
     no matter the casing fix. Fix: `detect()` no longer requires DOB at
     all — it now pairs the name pattern with a brand/product-name anchor
     ("Functional Health Report" / "Practitioner Report", generic marketing
     copy, confirmed present and not patient data) for specificity instead.
     `extract()` still opportunistically pulls DOB when the pattern *does*
     match (some variants do print one), it's just no longer required.
     This dovetails with item 9's decision to drop DOB restoration
     entirely — this template no longer depends on DOB being present or
     even parseable at all.
   Verified against all 5 real `Lab-templates/*.pdf` samples via
   `scratch/verify_deidentify_safe.py`: full PASS, including the new
   sample (`optimal_dx`, 1 field — name only, as expected for a
   DOB-less variant, 67 redactions, clean, visible). Watcher restarted
   after these changes.
   **Action needed from the user:** the original files still sitting in
   `Needs Review/MelissaSlater-OptimalDX-Practitioner-Aug-22-2026*.pdf`
   were never actually de-identified (they're untouched originals) — move
   one back into `Incoming` to actually process it now that the template
   is fixed, then the `Needs Review` copies can be deleted.
