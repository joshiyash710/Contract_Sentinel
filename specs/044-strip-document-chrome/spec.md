# Feature 044 — Strip document-chrome artifacts from extracted text

Branch: `feature/044-strip-document-chrome` (per constitution §11).

## 1. Problem statement

Contracts filed on SEC EDGAR (and the CUAD eval corpus drawn from them) carry a repeating
**page-footer artifact** that the PDF/DOCX parser bleeds into the extracted text at every page break:

```
Source: ARCONIC ROLLED PRODUCTS CORP, 10-12B, 12/17/2019
```

An **offline measurement of the cached 6-document large-doc run** found this is **systemic, not a
one-off**: **103 of 981 segmented clauses (10.5%) contain a `Source: <COMPANY>, <FORM>, <DATE>` EDGAR
footer**, and 13.8% contain some document-chrome artifact. Because the footer lands **inside**
`extracted_text` before clause splitting, it causes three concrete harms observed in the diagnostic:

1. **Spurious findings** — a clause that is mostly an EDGAR header (e.g. `"9 Source: ARMSTRONG
   FLOORING, INC., 8-K, 1/7/2019 directors, officers, agents…"`) was surfaced as a `medium`-risk
   finding: a false flag caused purely by document chrome.
2. **Broken segmentation** — a footer injected at a page boundary can split a real clause or become
   its own noise "clause."
3. **Polluted retrieval** — the artifact text is embedded into the CRAG query vector, degrading KB
   match quality (the run went 87% web-fallback).

Real users uploading real EDGAR/filed contracts hit the same artifact, so this is a genuine ingestion-
quality bug, not an eval-only concern.

### Position relative to the constitution
This cleans `extracted_text` **inside the existing IngestAgent (Node 1)** before it is returned — the
7-node graph, edges, and `ContractState` shape are untouched (§2). The cleaning is gated by a **named
config flag** (§3), reversible to today's behavior. The recognizable-chrome patterns are a **fixed
document-format vocabulary** (like the recital-keyword / ordinal-word lists), so per §3 they live
inline in the cleaner module, not as tunable thresholds. Per §7 the cleaner is a pure function,
TDD-unit-tested without Ollama/IO. Developed on `feature/044-strip-document-chrome` (§1/§11).

## 2. Inputs and outputs

### 2.1 New config (§3)
- `INGEST_STRIP_DOCUMENT_CHROME_ENABLED: bool` — master switch. **Default `True`.** `False` ⇒
  byte-for-byte today's `extracted_text` (no stripping), for reversibility.

### 2.2 Behavior change (`ingest_agent.py`)
On the success path, before returning, run a deterministic cleaner over the parsed text:
`extracted_text = strip_document_chrome(result.text)` when the flag is on. The cleaner removes lines
that match recognizable document-chrome patterns and leaves all other text **byte-identical**.

### 2.3 What is stripped (conservative, high-precision)
- **EDGAR source footer:** a line of the form `Source: <COMPANY>, <FORM-TYPE>, <DATE>` where
  `<FORM-TYPE>` is an SEC form id (`10-Q`, `10-K`, `8-K`, `S-1`, `S-4`, `10-12B`, `1-A`, `F-1`,
  `10-KA`, `EX-…`, etc.) and `<DATE>` is `M/D/YYYY`.
- Adjacent EDGAR chrome commonly on the same footer: a bare page-number line, and a
  `Powered by … Document Research` / Morningstar boilerplate line, when present.

### 2.4 What is explicitly NOT stripped
- **`[***]` redactions** — these mark redacted commercial terms (price, quantity) and are *meaningful*
  legal content; they stay.
- Any line that merely *contains* the word "Source" (e.g. `"Source code shall be delivered…"`) — the
  pattern requires the full `Source: …, <FORM>, <DATE>` shape.
- Ordinary clause text of any kind. The cleaner only ever *removes recognized chrome lines*; it never
  rewrites or reflows substantive text.

### 2.5 Output
No new state field, no boundary-model change, no report/schema change. `extracted_text` is the same
string minus recognized chrome lines. Downstream (segmentation, CRAG, Self-RAG, scoring) is unchanged;
it simply receives cleaner input → fewer artifact-driven false flags and better segmentation/retrieval.

## 3. Resolved decisions (inline)
- **D1 — Clean pre-segmentation, in IngestAgent.** The artifact must be gone before `split_by_regex`
  sees it; the single convergence point is `extracted_text` at the IngestAgent success return.
- **D2 — Conservative, pattern-anchored, high-precision.** Strip only lines matching the full EDGAR
  footer shape (company + SEC form id + date), not anything that loosely resembles a header. A missed
  artifact is a minor quality loss; stripping real text is a correctness bug — so bias to under-strip.
- **D3 — Reversible config flag (§3).** `INGEST_STRIP_DOCUMENT_CHROME_ENABLED=False` ⇒ today's exact
  `extracted_text`. Fixed patterns inline (not tunable → not a §3 numeric threshold).
- **D4 — Never touch `[***]` redactions.** They are content, not chrome (explicit negative test).
- **D5 — Line-oriented, deterministic, pure.** Operate on whole lines of the parsed text; no RNG, no
  I/O, no Ollama. Idempotent (re-running on cleaned text is a no-op).

## 4. Acceptance criteria (pytest — all offline, no Ollama)
- **AC-1 (strips the EDGAR footer):** text containing `Source: ARCONIC ROLLED PRODUCTS CORP, 10-12B,
  12/17/2019` on its own line returns with that line removed and the surrounding clause text intact.
- **AC-2 (multiple forms/dates):** footers with `8-K`, `10-Q`, `S-1`, `10-KA`, `EX-10.2` form ids and
  various `M/D/YYYY` dates are all removed.
- **AC-3 (preserves substantive text):** a line like `"Source code shall be delivered to Buyer."` and a
  clause containing `[***]` are **unchanged** (negative controls).
- **AC-4 (reduces a real artifact clause):** given the observed Armstrong header-polluted clause
  (`"9 Source: ARMSTRONG FLOORING, INC., 8-K, 1/7/2019 directors, officers…"`), the footer portion is
  removed while the substantive `"directors, officers…"` remainder is retained (so the clause is no
  longer chrome-dominated).
- **AC-5 (integration + reversibility):** with the flag ON, `ingest_agent` returns `extracted_text`
  with the footer stripped; with `INGEST_STRIP_DOCUMENT_CHROME_ENABLED=False`, `extracted_text` is
  identical to today (no stripping). A `test_config` assertion checks the flag is a bool.
- **AC-6 (idempotent + no architecture change):** `strip_document_chrome(strip_document_chrome(t)) ==
  strip_document_chrome(t)`. `git diff` touches only `app/config.py`, `ingest_agent.py`, a new cleaner
  helper module, and their tests — no graph/edge/`ContractState`/migration/Self-RAG change. Whole
  `pytest` green.
- **AC-7 (determinism):** pure function of the input text + config; repeated calls identical.

## 5. Edge cases
- **EC-1 — Footer with trailing page number** (`"Source: X, 8-K, 1/1/2020"` then a lone `"12"` line) →
  the footer line is stripped; a bare page-number line adjacent to a stripped footer is also removed.
- **EC-2 — Footer embedded mid-line** (parser glued it to adjacent text, as in AC-4) → remove only the
  matched footer span, keep the rest of the line.
- **EC-3 — No artifacts present** → text returned unchanged (common case; must be a no-op).
- **EC-4 — Flag off** → today's behavior exactly (D3).
- **EC-5 — `[***]` / "Source" in real content** → never stripped (D4/AC-3).
- **EC-6 — Empty / whitespace text** → returned unchanged.

## 6. Out of scope
- General OCR/parse-quality cleanup, de-hyphenation, whitespace normalization — this feature targets
  only the recognizable EDGAR/document-chrome footer.
- Non-EDGAR headers/footers from other document sources (can be added to the pattern set later).
- Changing segmentation, CRAG, or any downstream node — 044 only supplies cleaner input.
- Re-labeling gold or re-tuning thresholds — separate efforts.

## 7. Evaluation (metrics to log)
Deterministic unit tests (AC-1…AC-7). Optional confirmation on the cached corpus: the
`Source:`-artifact clause count should drop toward zero after re-ingest (the 10.5% measured here). No
live/harness run is required to validate the cleaner; a full re-eval belongs with the model-upgrade
work, not here.

## 8. Notes for plan.md / tasks.md (pointers)
- **Config:** add `INGEST_STRIP_DOCUMENT_CHROME_ENABLED` (bool, default True) to `app/config.py`.
- **Cleaner:** a pure helper (e.g. `app/graph/nodes/ingest/text_cleaner.py` or alongside ingest):
  `strip_document_chrome(text: str) -> str`, compiling the chrome patterns once at import; line-
  oriented, idempotent, no I/O.
- **Wire-in:** in `ingest_agent.py` success path (line ~218), gate on the flag and clean
  `result.text` before assigning `extracted_text`. Read the flag by bare module name for monkeypatch.
- **Tests:** new `tests/unit/test_text_cleaner.py` (AC-1..AC-4, AC-6, AC-7 pure); extend
  `tests/unit/test_ingest_agent.py` for AC-5 (integration + reversibility); add the `test_config` bool
  assertion. TDD failing-first.
