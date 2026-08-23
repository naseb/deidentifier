"""
Registry of known lab-report templates.

Each template module exposes:
    NAME             - short identifier, e.g. "quest"
    REPLACEMENT_MAP  - {field_label: replacement_string_or_format_string}
                        ("{case_code}" is substituted in by the caller)
    detect(doc, full_text, page1_text) -> bool
    extract(doc, full_text, page1_text) -> dict of {field_label: value}

Templates are tried in order; the first whose detect() returns True is used,
and only that template's extract() runs. This keeps each lab's patterns
isolated from the others -- adding a new lab company means adding one new
module and one line here, without touching any existing template's logic or
risking cross-template false-positive matches.

If no template detects the document, the caller gets back an empty dict and
should route the file to manual review rather than guess.
"""

from . import optimal_dx, quest, genova_oap_nutripath, genova_sibo

TEMPLATES = [
    optimal_dx,
    quest,
    genova_oap_nutripath,
    genova_sibo,
]


def find_identifiers_for_doc(doc):
    """
    Returns (identifiers: dict, replacement_map: dict, template_name: str|None).
    identifiers is {} and template_name is None if no template detected a match.
    """
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    page1_text = doc[0].get_text()

    for template in TEMPLATES:
        if template.detect(doc, full_text, page1_text):
            identifiers = template.extract(doc, full_text, page1_text)
            if identifiers:
                return identifiers, template.REPLACEMENT_MAP, template.NAME

    return {}, {}, None
