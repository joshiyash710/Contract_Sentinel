# Feature 044 — Technical plan: strip document-chrome artifacts

Branch: `feature/044-strip-document-chrome` (per constitution §11).

Derived from `spec.md`. Adds a pure, deterministic `strip_document_chrome(text)` cleaner that removes
recognizable EDGAR page-footer artifacts from `extracted_text` inside IngestAgent (Node 1) before
segmentation. **No graph/edge/`ContractState`/migration change** — cleaner input only, gated by a §3
flag.

## 0. Scope of change (files touched)

Per **AC-6** the `git diff main` must touch only:
1. `backend/app/config.py` — add `INGEST_STRIP_DOCUMENT_CHROME_ENABLED` (bool, default True).
2. `backend/app/graph/nodes/ingest/text_cleaner.py` — **NEW** pure `strip_document_chrome`.
   (New `ingest` subpackage under `nodes/`; add its `__init__.py`.)
3. `backend/app/graph/nodes/ingest_agent.py` — module alias + gated clean of `result.text` at the
   success return.
4. `backend/tests/unit/test_text_cleaner.py` — **NEW** pure-cleaner tests (AC-1..AC-4, AC-6, AC-7).
5. `backend/tests/unit/test_ingest_agent.py` — integration + reversibility (AC-5).
6. `backend/tests/unit/test_config.py` — flag bool assertion (AC-5).

No other file changes.

## 1. Config change (`app/config.py`)

Near the ingest constants, add (mirroring `DETERMINISTIC_CLAUSE_TYPING_ENABLED` /
`HONEST_FAILURE_SURFACING_ENABLED` bool convention):

```python
INGEST_STRIP_DOCUMENT_CHROME_ENABLED: bool = True
# Master switch (feature 044). When True, IngestAgent removes recognizable EDGAR page-footer chrome
# (`Source: <COMPANY>, <FORM>, <DATE>` + an immediately-adjacent bare page-number line) from
# extracted_text before clause segmentation. False ⇒ byte-for-byte today's extracted_text. Reversible.
```

## 2. Cleaner (`app/graph/nodes/ingest/text_cleaner.py`, NEW)

Pure, deterministic, line-oriented, no I/O, no Ollama. **Two composable passes** (spec-reviewer note 1
— mid-line excision is a DISTINCT path from whole-line removal):

```python
import re

# SEC form ids that appear in the EDGAR "Source:" footer. Fixed document-format vocabulary (§3 inline,
# like the recital-keyword list) — NOT a tunable threshold. The FIRST branch handles the
# registration-form family "10-12B" / "10-12G" (digits-digits+letters) — the ARCONIC footer in AC-1;
# the second handles "10-Q"/"8-K"/"10-KA" (digits-letters). Verified to match 10-12B, 10-Q, 8-K, S-1,
# 10-KA, EX-10.2, F-1, 1-A and to reject the AC-3 negatives.
_SEC_FORM = r"(?:\d{1,2}-\d{1,3}[A-Z]{0,3}|\d{1,2}-[A-Z]{1,3}\d*|S-\d+[A-Z]?|F-\d+[A-Z]?|EX-[\w.\-]+|1-A|POS[\s-]?AM)"
# The EDGAR footer span: "Source: <COMPANY>, <FORM>, M/D/YYYY". Anchored on the form-id + date shape so
# it never matches prose that merely contains "Source". Case-insensitive on the leading token only.
_EDGAR_FOOTER = re.compile(
    rf"Source:\s*.+?,\s*{_SEC_FORM}\s*,\s*\d{{1,2}}/\d{{1,2}}/\d{{4}}",
    re.IGNORECASE,
)
_BARE_PAGE_NUM = re.compile(r"^\s*\d{1,4}\s*$")


def strip_document_chrome(text: str) -> str:
    """Remove recognizable EDGAR page-footer chrome from parsed contract text.
    Pass 1 (mid-line excision): delete any _EDGAR_FOOTER span wherever it occurs in a line, keeping
      the rest of that line (EC-2 / AC-4 — parser sometimes glues the footer to adjacent text).
    Pass 2 (whole-line drop): drop a line that is now empty/whitespace ONLY because a footer was
      excised, and drop a bare page-number line ONLY when it is immediately adjacent (prev or next
      physical line) to a line from which a footer was excised (EC-1). Never drops a bare-number line
      that is not footer-adjacent. Idempotent; pure."""
    if not text:
        return text
    lines = text.split("\n")
    footer_line = [False] * len(lines)
    for i, ln in enumerate(lines):
        new = _EDGAR_FOOTER.sub("", ln)
        if new != ln:
            footer_line[i] = True
            lines[i] = new
    out = []
    for i, ln in enumerate(lines):
        if footer_line[i] and ln.strip() == "":
            continue  # line was pure footer → drop
        if _BARE_PAGE_NUM.match(ln) and (
            (i > 0 and footer_line[i - 1]) or (i + 1 < len(lines) and footer_line[i + 1])
        ):
            continue  # bare page number hugging a footer → drop (EC-1)
        out.append(ln)
    return "\n".join(out)
```

- `_SEC_FORM` covers `10-Q/10-K/8-K/10-12B/10-KA/S-1/S-4/F-1/1-A/EX-…` etc. (spec §2.3/AC-2).
- **Never touches `[***]`** or any line lacking the full `Source: …, <FORM>, <date>` shape (AC-3/EC-5).
- **"Adjacent" is precisely "the immediately preceding or following physical line"** (spec-reviewer
  note 2), and only when that neighbor had a footer excised — a standalone bare-number line is kept.
- **Idempotent (spec-reviewer note 3):** pass 1 on already-cleaned text finds no footer → `footer_line`
  all False → pass 2 drops nothing. A dedicated mid-line idempotence test pins this (AC-6).

## 3. Wire-in (`ingest_agent.py` success return, ~line 218)

Add a module alias next to the other re-exposed config names:
```python
from app.graph.nodes.ingest.text_cleaner import strip_document_chrome
INGEST_STRIP_DOCUMENT_CHROME_ENABLED = _config.INGEST_STRIP_DOCUMENT_CHROME_ENABLED
```
At the success return, clean before assigning:
```python
extracted = result.text
if INGEST_STRIP_DOCUMENT_CHROME_ENABLED:
    extracted = strip_document_chrome(result.text)
...
"extracted_text": extracted,
```
Read the flag by bare module name so the reversibility test can monkeypatch it. Nothing else in the
node changes; the error paths (which return `""`) are untouched.

## 4. Control-flow / correctness
- **Single hook (D1):** cleaning happens once, on the IngestAgent success `extracted_text`, before
  Node 2's `split_by_regex` ever sees it. No downstream node changes.
- **Reversibility (D3):** flag False ⇒ `extracted = result.text` unchanged ⇒ byte-identical to today.
- **No shape change:** `extracted_text` stays a `str`; `ContractState`, edges, and every downstream
  contract are identical.
- **Bias to under-strip (D2):** the footer regex requires company + SEC-form-id + `M/D/YYYY`; prose
  with "Source" or a lone page number in normal text is never removed.
- **Cannot raise on normal input:** guards empty text; pure regex over `str`.

## 5. Test plan (TDD, `tests/unit/`)
Failing-first per §7. All offline (pure function; ingest integration mocks the parser).

- **AC-1/AC-2 (`test_text_cleaner.py`):** footers with `10-12B` (the ARCONIC canonical case — MUST be
  an explicit case so the registration-form regex branch is pinned), `8-K`, `10-Q`, `S-1`, `10-KA`,
  `EX-10.2` + various `M/D/YYYY` dates on their own line are removed; surrounding clause text intact.
- **AC-3 negative controls:** `"Source code shall be delivered to Buyer."` unchanged; a clause with
  `[***]` unchanged; a bare `"12"` line NOT adjacent to a footer unchanged.
- **AC-4 / EC-2 mid-line:** `"9 Source: ARMSTRONG FLOORING, INC., 8-K, 1/7/2019 directors, officers…"`
  → footer span removed, `"9  directors, officers…"` remainder retained (clause no longer chrome-
  dominated).
- **EC-1:** a footer line followed by a lone `"12"` → both removed; the same `"12"` with no adjacent
  footer → kept.
- **AC-6 idempotence:** `strip(strip(t)) == strip(t)` for a whole-line case AND a mid-line case
  (dedicated test, spec-reviewer note 3). **AC-7 determinism:** repeated calls identical.
- **AC-5 integration + reversibility (`test_ingest_agent.py`):** mock the parser so `result.text`
  contains an EDGAR footer; with the flag ON the returned `extracted_text` has it stripped; monkeypatch
  `ingest_agent.INGEST_STRIP_DOCUMENT_CHROME_ENABLED = False` → `extracted_text == result.text`.
- **AC-5 config (`test_config.py`):** `INGEST_STRIP_DOCUMENT_CHROME_ENABLED` is a `bool`.
- **AC-6 scope:** confirm only the six allow-listed files change; whole `pytest` green (pin any
  surprised existing ingest test the way 027 did, never weaken).

## 6. Risks / limitations
- **EDGAR-only patterns:** other document sources' headers/footers aren't covered (spec §6) — additive
  later. Acceptable: 044 removes the measured 10.5% EDGAR artifact.
- **Under-strip by design (D2):** an unusual footer variant may slip through; preferred over stripping
  real text. Measured impact, not a correctness risk.

## 7. Merge
- Whole `pytest` green; `git diff --name-only main` = the six allow-listed files (+ `specs/044-**`).
  Rebase `main`, merge `feature/044-strip-document-chrome`, delete branch (`git-finish`).
