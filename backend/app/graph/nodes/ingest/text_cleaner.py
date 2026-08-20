"""Document-chrome cleaner (feature 044).

A pure, deterministic, line-oriented cleaner that removes recognizable EDGAR page-footer artifacts
(`Source: <COMPANY>, <FORM>, <DATE>`) from parsed contract text before clause segmentation. Such
footers repeat at every page break in SEC-filed contracts (and the CUAD corpus), bleed into
`extracted_text`, and cause spurious findings / broken segmentation / polluted retrieval.

Constitution rules observed:
  §3 — fixed document-format vocabulary lives inline (like the recital-keyword list), NOT a tunable
        threshold; the master switch is the §3 config flag INGEST_STRIP_DOCUMENT_CHROME_ENABLED
  §7 — pure function, TDD-unit-tested offline (no Ollama, no I/O, no RNG); idempotent

Conservative by design (D2): only lines/spans matching the FULL EDGAR footer shape (company + SEC form
id + M/D/YYYY date) are removed. `[***]` redactions and prose merely containing "Source" are never
touched. The cleaner only ever removes recognized chrome — it never rewrites substantive text.
"""

import re

# SEC form ids that appear in the EDGAR "Source:" footer. Fixed document-format vocabulary (§3 inline).
# First branch handles the registration-form family "10-12B"/"10-12G" (digits-digits+letters — the
# ARCONIC footer); second handles "10-Q"/"8-K"/"10-KA" (digits-letters); plus S-/F-/EX-/1-A/POS AM.
_SEC_FORM = (
    r"(?:\d{1,2}-\d{1,3}[A-Z]{0,3}|\d{1,2}-[A-Z]{1,3}\d*|S-\d+[A-Z]?|F-\d+[A-Z]?"
    r"|EX-[\w.\-]+|1-A|POS[\s-]?AM)"
)

# The EDGAR footer span: "Source: <COMPANY>, <FORM>, M/D/YYYY". Anchored on the SEC-form-id + date
# shape so it never matches prose that merely contains "Source". The trailing date bounds the `.+?`.
_EDGAR_FOOTER = re.compile(
    rf"Source:\s*.+?,\s*{_SEC_FORM}\s*,\s*\d{{1,2}}/\d{{1,2}}/\d{{4}}",
    re.IGNORECASE,
)

_BARE_PAGE_NUM = re.compile(r"^\s*\d{1,4}\s*$")


def strip_document_chrome(text: str) -> str:
    """Remove recognizable EDGAR page-footer chrome from parsed contract text.

    Pass 1 (mid-line excision): delete any ``_EDGAR_FOOTER`` span wherever it occurs in a line,
      keeping the rest of that line (EC-2 / AC-4 — the parser sometimes glues the footer to adjacent
      text). Records which lines had a footer excised.
    Pass 2 (whole-line drop): drop a line that is empty/whitespace *only because* a footer was
      excised, and drop a bare page-number line *only when* it is immediately adjacent (the physical
      preceding or following line) to a footer-excised line (EC-1). A bare-number line that is not
      footer-adjacent is kept.

    Pure, deterministic, idempotent (re-running on cleaned text finds no footer → no-op).
    """
    if not text:
        return text

    lines = text.split("\n")
    footer_line = [False] * len(lines)
    for i, ln in enumerate(lines):
        cleaned = _EDGAR_FOOTER.sub("", ln)
        if cleaned != ln:
            footer_line[i] = True
            lines[i] = cleaned

    out = []
    for i, ln in enumerate(lines):
        if footer_line[i] and ln.strip() == "":
            continue  # the line was pure footer → drop it entirely
        if _BARE_PAGE_NUM.match(ln) and (
            (i > 0 and footer_line[i - 1]) or (i + 1 < len(lines) and footer_line[i + 1])
        ):
            continue  # bare page number hugging a stripped footer (EC-1)
        out.append(ln)
    return "\n".join(out)
