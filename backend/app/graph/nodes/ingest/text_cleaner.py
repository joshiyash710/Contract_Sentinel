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

    Pure, deterministic, idempotent (re-running on cleaned text finds no footer → no-op). Thin wrapper
    over strip_document_chrome_tracked (feature 055) — byte-identical return for existing callers.
    """
    return strip_document_chrome_tracked(text)[0]


def strip_document_chrome_tracked(text: str):
    """Feature 055: like strip_document_chrome, but also return the ordered, non-overlapping list of
    removed ``[start, end)`` ranges in ORIGINAL (pre-strip) coordinates, so a char->(page,bbox) span
    map over the original text can be remapped to the cleaned text (see remap_spans). Returns
    ``(cleaned_text, deletions)``. The cleaned text is byte-identical to the pre-055 strip output.

    Deletion model (contiguous cuts): a KEPT line with a mid-line footer records each ``_EDGAR_FOOTER``
    match range; a DROPPED line records its whole range plus its following newline
    (``[starts[i], starts[i+1])``) — dropping a middle line "A\\nB\\nC"→"A\\nC" is exactly the cut
    ``[start(B), start(C))``. A line is either kept-with-excision OR dropped, never both recorded, so the
    ranges stay non-overlapping and ascending.
    """
    if not text:
        return text, []

    lines = text.split("\n")
    starts = []  # original start offset of each line (content; the "\n" follows at start+len)
    pos = 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1  # +1 for the "\n" separator

    footer_line = [bool(_EDGAR_FOOTER.search(ln)) for ln in lines]

    deletions = []
    kept = []
    n = len(lines)
    for i, ln in enumerate(lines):
        matches = list(_EDGAR_FOOTER.finditer(ln))
        excised = _EDGAR_FOOTER.sub("", ln) if matches else ln
        drop = (matches and excised.strip() == "") or (
            _BARE_PAGE_NUM.match(ln)
            and ((i > 0 and footer_line[i - 1]) or (i + 1 < n and footer_line[i + 1]))
        )
        if drop:
            if i < n - 1:
                deletions.append((starts[i], starts[i + 1]))  # line + following newline
            else:  # last line: also remove the preceding newline (if any content precedes)
                deletions.append((max(0, starts[i] - 1), len(text)))
        else:
            for m in matches:
                deletions.append((starts[i] + m.start(), starts[i] + m.end()))
            kept.append(excised)

    deletions.sort()
    return "\n".join(kept), deletions


def remap_spans(page_spans, deletions):
    """Feature 055: translate page_spans (offsets into the ORIGINAL text) to CLEANED-text offsets, given
    the ascending non-overlapping ``deletions`` from strip_document_chrome_tracked. A span fully inside
    a deletion is dropped; otherwise its offsets shift left by the total length of deletions ending at or
    before its start. bbox/page unchanged. Pure."""
    if not page_spans:
        return page_spans
    if not deletions:
        return [dict(s) for s in page_spans]
    out = []
    for s in page_spans:
        start, end = s["start"], s["end"]
        if any(d0 <= start and end <= d1 for (d0, d1) in deletions):
            continue  # fully inside a removed range
        shift = sum(d1 - d0 for (d0, d1) in deletions if d1 <= start)
        out.append({**s, "start": start - shift, "end": end - shift})
    return out
