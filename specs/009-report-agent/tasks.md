# ReportAgent Implementation Tasks

Reference documents:
- Spec: `specs/009-report-agent/spec.md`
- Plan: `specs/009-report-agent/plan.md`
- State schema: `specs/001-contract-state-schema.md`
- Tech stack: `specs/002-tech-stack.md`
- Constitution: `specs/000-constitution.md`

All file paths below are relative to `backend/` unless stated otherwise.

**Workflow reminders:**
- Follow TDD per constitution §7 — write tests, confirm they FAIL, then implement to make them PASS.
- This feature is **Node 7 (ReportAgent)**, the **terminal** node of the fixed 7-node pipeline. It owns **one graph node** (`report`) plus the **fan-in rewiring** of the two feature-008 placeholder edges (`redline → report`, `skip_redline → report`) and `report → END`.
- **ReportAgent makes NO LLM call, NO retrieval, NO routing decision, and runs NO circuit breaker** (spec §7.2, D3). It is a deterministic function of `ContractState` plus one file write. There is no `ollama`, no timeout/model/circuit-breaker constant, no drafter — do not add any.
- ReportAgent returns ONLY the state keys it updates per constitution §5 (Partial-Update Rule): `report_path`, `evidence_trail`, `current_node`, `node_timings` — **plus `error_count: 1` in the one case the report file write fails** (spec §7.6 / AC-19). Never any other key. In particular it NEVER returns `processing_completed_at` (D2), never returns a `clauses` key, and never modifies `clauses`.
- All paths/thresholds live in `app/config.py` per constitution §3 — never hardcode inline.
- **Boundary Pydantic model (constitution §4):** the report structure is a Pydantic model in `app/models/report.py`, built FROM the TypedDict `ContractState` and never stored IN graph state. The JSON output is `model.model_dump_json()`; the Markdown renderer walks the same model, so the two formats cannot structurally drift (D1).
- **State minimality (constitution §6):** the report BODY goes to files; only `report_path` (a string) enters state. The only report-derived content in state is the bounded `evidence_trail`, whose per-row `evidence_text` is truncated to `REPORT_EVIDENCE_TEXT_MAX_CHARS`.

**The eight locked design decisions (spec §8a D1–D8):**
- **D1** — Markdown body + sibling JSON; `report_path` points at the Markdown. Both dependency-free.
- **D2** — the graph **runner** (not ReportAgent) stamps `processing_completed_at`. The node never writes it. *Integration assumption:* no runner currently stamps it, so it is presently written by nobody — recorded here, owned by a future runner/API feature.
- **D3** — no LLM executive summary in Phase 1. Fully deterministic.
- **D4** — clean (non-validated) clauses are **counted, not enumerated** (never re-surface `DISCARDED` content — constitution §2.4).
- **D5** — `evidence_trail` covers **validated findings only**, one row per (finding, snippet).
- **D6** — deterministic filenames `{document_id}.md` / `.json` under `data/reports/`; a re-run overwrites in place.
- **D7** — MCP Drive/Gmail delivery is a separate future feature (`specs/010-*`), out of scope.
- **D8** — `evidence_trail.retrieved_at` = **one** report-generation UTC timestamp, taken once at node start and shared by all rows (CRAG persists no per-snippet retrieval time; `make_snippet()` at `retrievers/__init__.py:34` produces exactly `{snippet_text, source_reference}`). This narrows `001` §3's "when retrieved/validated" gloss to "when the trail row was compiled" — documentation-only, no schema change.
- **Write order (D1 / AC-19a):** write JSON **first**, then Markdown, so `report_path` (the Markdown) is only set once its JSON sibling exists; on a Markdown-after-JSON failure, unlink the orphan JSON. On any write failure → `report_path = None`, `error_count: 1`, `evidence_trail` still emitted.
- Branch: `feature/009-report-agent` per constitution §11.

---

## Task 0: Create feature branch

- [ ] Confirm `specs/009-report-agent/spec.md`, `plan.md`, and `tasks.md` all exist and are approved (constitution §1 / §11 gate).
- [ ] From an up-to-date `main`, create and check out `feature/009-report-agent` (the `git-start` skill does this mechanically).

**Why**: Per constitution §11, every feature is developed on its own branch. Redline (008) is already merged to `main`.

**Verify**: `git branch --show-current` prints `feature/009-report-agent`.

**Note**: The working tree has an untracked `specs/009-report-agent/`. Confirm with the user whether the spec docs should be committed before branching, so 009 starts from a clean tree (same as the 007/008 start).

---

## Task 1: Write config tests for the Report constants (confirm FAILING)

- [ ] Open `tests/unit/test_config.py`
- [ ] Add 4 new test functions:

```python
def test_report_constants_match_spec():
    """Verify Report constants match specs/009 §6."""
    from app.config import (
        REPORT_OUTPUT_DIR,
        REPORT_MD_FILENAME_TEMPLATE,
        REPORT_JSON_FILENAME_TEMPLATE,
        REPORT_EVIDENCE_TEXT_MAX_CHARS,
    )
    assert REPORT_OUTPUT_DIR == "data/reports"
    assert REPORT_MD_FILENAME_TEMPLATE == "{document_id}.md"
    assert REPORT_JSON_FILENAME_TEMPLATE == "{document_id}.json"
    assert REPORT_EVIDENCE_TEXT_MAX_CHARS == 2000


def test_report_constants_correct_types():
    """str for the dir + templates; int for the char cap."""
    from app import config
    assert isinstance(config.REPORT_OUTPUT_DIR, str)
    assert isinstance(config.REPORT_MD_FILENAME_TEMPLATE, str)
    assert isinstance(config.REPORT_JSON_FILENAME_TEMPLATE, str)
    assert isinstance(config.REPORT_EVIDENCE_TEXT_MAX_CHARS, int)


def test_report_filename_templates_have_document_id():
    """Both templates are keyed on document_id and differ only by extension (D6)."""
    from app.config import (
        REPORT_MD_FILENAME_TEMPLATE,
        REPORT_JSON_FILENAME_TEMPLATE,
    )
    assert "{document_id}" in REPORT_MD_FILENAME_TEMPLATE
    assert "{document_id}" in REPORT_JSON_FILENAME_TEMPLATE
    assert REPORT_MD_FILENAME_TEMPLATE.endswith(".md")
    assert REPORT_JSON_FILENAME_TEMPLATE.endswith(".json")
    # Same stem → the pair always stays in sync on a re-run
    assert (REPORT_MD_FILENAME_TEMPLATE.rsplit(".", 1)[0]
            == REPORT_JSON_FILENAME_TEMPLATE.rsplit(".", 1)[0])


def test_report_no_llm_constant():
    """Node 7 makes no LLM call (D3) — no timeout/model/circuit-breaker constant."""
    from app import config
    assert not hasattr(config, "REPORT_TIMEOUT_SECONDS")
    assert not hasattr(config, "REPORT_LLM_CIRCUIT_BREAKER_THRESHOLD")
    assert not hasattr(config, "REPORT_MODEL_NAME")
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — `test_report_constants_match_spec`, `test_report_constants_correct_types`, and `test_report_filename_templates_have_document_id` must FAIL (`ImportError` — constants don't exist yet). `test_report_no_llm_constant` may already PASS. All existing config tests (Ingest + ClauseSplitter + CRAG + Self-RAG + RiskScore + Redline) must still PASS.

---

## Task 2: Add the Report constants to config

- [ ] Open `app/config.py`
- [ ] **No new import needed** — all values are plain `str` / `int` (Report needs no enum). Leave the existing `from app.graph.state import RiskLevel` at `config.py:11` untouched.
- [ ] Append a new `# ── Report thresholds` block at the end of the file (pure addition — no rename, no placeholder to replace):

```python
# ── Report thresholds ──────────────────────────────────────────────────────────
# Source: specs/009-report-agent/spec.md §6

REPORT_OUTPUT_DIR: str = "data/reports"
# Directory (backend/-relative, mirroring CRAG_KB_INDEX_PATH's anchoring) where
# ReportAgent writes serialized report files. Created if absent. (spec §6, D6)

REPORT_MD_FILENAME_TEMPLATE: str = "{document_id}.md"
# Human-readable Markdown report; report_path points here (D1). Deterministic on
# document_id so a re-run overwrites in place (D6, Edge Case 9).

REPORT_JSON_FILENAME_TEMPLATE: str = "{document_id}.json"
# Machine-readable JSON sibling written alongside the Markdown at the same stem
# (D1). Same deterministic-overwrite scheme (D6).

REPORT_EVIDENCE_TEXT_MAX_CHARS: int = 2000
# Per-row cap on evidence_trail `evidence_text` before it is written to state, to
# bound persisted state size (constitution §6; Edge Case 6). Mirrors the truncation
# discipline of RISK_RATIONALE_MAX_CHARS / REDLINE_REWRITE_MAX_CHARS.
```

- [ ] Do NOT add any LLM/timeout/model/circuit-breaker constant (D3).

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — all config tests (through Report) must now PASS.

---

## Task 3: Write unit tests for the Pydantic report models (confirm FAILING)

- [ ] Create file `tests/unit/test_report_models.py`
- [ ] The import `from app.models.report import ContractReport, ReportFinding, ReportSummary, ReportEvidence` will fail until Task 4 — expected for TDD.
- [ ] Write these 5 test functions (plan §2 model matrix):

| Test function | Verifies |
|---------------|----------|
| `test_contract_report_roundtrips_json` | A fully-built `ContractReport` serializes via `model_dump_json()` and re-parses (`model_validate_json`) to an equal model |
| `test_finding_rewrite_state_values` | `ReportFinding` accepts `rewrite_state` ∈ {`"rewritten"`, `"unavailable"`, `"not_eligible"`}; `suggested_rewrite` may be a str (for `"rewritten"`) or `None` |
| `test_summary_counts_are_ints` | `ReportSummary` fields are `int`; a built summary's `high+medium+low == validated_findings` and `clean_clauses == total_clauses - validated_findings` (constructed consistently) |
| `test_optional_fields_default_none` | `section_number` / `clause_type` / `risk_level` / `risk_rationale` / `path_taken` / `confidence_score` default to `None`; `evidence` and `findings` default to `[]` |
| `test_malformed_finding_raises` | Constructing `ReportFinding` without the required `clause_text` (or with a wrong-typed field) raises `pydantic.ValidationError` |

**Verify**: Run `python -m pytest tests/unit/test_report_models.py -v` — all 5 must FAIL (ImportError).

---

## Task 4: Implement the Pydantic report models

- [ ] Create file `app/models/report.py` (the `app/models/` dir currently holds only `.gitkeep` — this is the designated boundary-model home per constitution §4).
- [ ] **Imports**: `from typing import List, Optional`; `from pydantic import BaseModel, Field`. **No `app.graph.state` import** — the models are plain-typed (`str`/`int`/`Optional`); enum values are pre-normalized to `.value` strings by the assembler (Task 7) BEFORE model construction.
- [ ] Define the models exactly as plan §2 specifies:

```python
class ReportEvidence(BaseModel):
    source_reference: str
    snippet_text: str          # already truncated by the assembler to REPORT_EVIDENCE_TEXT_MAX_CHARS

class ReportFinding(BaseModel):
    clause_id: str
    position: int
    section_number: Optional[str] = None
    clause_type: Optional[str] = None          # ClauseType.value or None
    risk_level: Optional[str] = None           # RiskLevel.value or None
    risk_rationale: Optional[str] = None
    clause_text: str
    rewrite_state: str                         # "rewritten" | "unavailable" | "not_eligible"
    suggested_rewrite: Optional[str] = None    # present only when rewrite_state == "rewritten"
    path_taken: Optional[str] = None           # RetrievalPath.value or None
    confidence_score: Optional[float] = None
    evidence: List[ReportEvidence] = Field(default_factory=list)

class ReportSummary(BaseModel):
    total_clauses: int
    validated_findings: int
    clean_clauses: int                         # non-validated count only (D4)
    high: int
    medium: int
    low: int

class ContractReport(BaseModel):
    document_id: str
    original_filename: str
    uploaded_at: str
    processing_started_at: Optional[str] = None
    generated_at: str                          # the D8 report-generation timestamp
    ocr_used: bool = False
    ocr_confidence: Optional[float] = None
    ingest_error: Optional[dict] = None
    summary: ReportSummary
    findings: List[ReportFinding] = Field(default_factory=list)   # ordered by position
    node_timings: dict = Field(default_factory=dict)
    error_count: int = 0
```

- [ ] Add a module docstring stating this is a **boundary serialization model** (constitution §4), built from `ContractState`, never stored in graph state.

**Verify**: Run `python -m pytest tests/unit/test_report_models.py -v` — all 5 must PASS.

---

## Task 5: Create the renderers package marker (no dedicated TDD cycle)

- [ ] Create directory `app/graph/nodes/renderers/`
- [ ] Create file `app/graph/nodes/renderers/__init__.py` — a package marker with a module docstring that **re-exports** the pure helpers for a clean import surface:

```python
"""
Renderer modules for the ReportAgent node (Node 7).

report_assembler.py turns the TypedDict ContractState into a validated Pydantic
ContractReport (validated-only findings, ordered by position) and derives the
evidence_trail rows. markdown_renderer.py renders that model to a Markdown string.
Both are PURE — no file I/O, no LLM, no state mutation — so all report I/O and
failure handling live in report_agent.py. Mirrors the scorers/ / drafters/ /
validators/ / retrievers/ sub-package layout.
"""

from app.graph.nodes.renderers.report_assembler import (
    assemble_report,
    build_evidence_trail,
)
from app.graph.nodes.renderers.markdown_renderer import render_markdown

__all__ = ["assemble_report", "build_evidence_trail", "render_markdown"]
```

**Why**: mirrors the `scorers/` / `drafters/` / `validators/` / `retrievers/` layout. (The re-export import will error until Tasks 7 & 9 exist — that is fine; do not run this task's verify until after Task 9. If you prefer, create the `__init__.py` with only the docstring first and add the re-exports at the end of Task 9.)

**Verify** (after Task 9): `python -c "import app.graph.nodes.renderers; print('ok')"`.

---

## Task 6: Write unit tests for `assemble_report` + `build_evidence_trail` (confirm FAILING)

- [ ] Create file `tests/unit/test_report_assembler.py`
- [ ] The import `from app.graph.nodes.renderers.report_assembler import assemble_report, build_evidence_trail` will fail until Task 7 — expected for TDD.
- [ ] These are **pure functions** — no mocks, no I/O. Build fixture `ContractState` dicts directly. Helper `make_clause(...)` producing clause records with `{text, position, section_number, clause_type, final_status, risk_level, risk_rationale, suggested_rewrite (optional), evidence_snippets, confidence_score, path_taken}`. Use `ValidationStatus`, `RiskLevel`, `ClauseType`, `RetrievalPath` from `app.graph.state` in fixtures.
- [ ] Pass a fixed `generated_at = "2026-07-06T00:00:00+00:00"` and `evidence_text_max_chars` explicitly (e.g. 2000, or small for truncation tests).
- [ ] Write these 15 test functions (plan §2 assembler matrix):

| Test function | Verifies |
|---------------|----------|
| `test_only_validated_become_findings` | Mixed VALIDATED / DISCARDED / `final_status is None` → `report.findings` are exactly the VALIDATED records (AC-1) |
| `test_findings_ordered_by_position` | Findings sorted by `position` regardless of `clauses` dict insertion order (AC-2) |
| `test_summary_counts_correct` | `total_clauses`, `validated_findings`, `clean_clauses` (= total − validated), and H/M/L match the fixture (D4/AC-9) |
| `test_rewrite_state_three_way` | key **absent** → `rewrite_state == "not_eligible"`; value `None` → `"unavailable"`; non-empty str → `"rewritten"` with `suggested_rewrite` set (AC-8) |
| `test_evidence_text_truncated` | A snippet `snippet_text` longer than the cap is truncated to `evidence_text_max_chars` in the model (AC-12a, Edge Case 6) |
| `test_missing_snippet_fields_placeholder` | Snippet missing `snippet_text` / `source_reference` → a defined placeholder, no `KeyError` (Edge Case 7) |
| `test_empty_evidence_finding` | Validated finding with `evidence_snippets == []` / `None` → `finding.evidence == []`, no crash (AC-7) |
| `test_missing_risk_level_placeholder_path` | Validated finding with `risk_level is None` still assembles (renders as placeholder downstream — Edge Case 4) |
| `test_ingest_error_minimal_report` | `ingest_error` set → `findings == []`, `report.ingest_error` populated, zeroed `ReportSummary` (Edge Case 1 / AC-20) |
| `test_enum_or_str_risk_level` | `risk_level` given as a `RiskLevel` enum **or** its str value both normalize to the same `.value` (checkpoint round-trip robustness) |
| `test_assembler_does_not_mutate_state` | Deep-copy the input `state`; after `assemble_report`, assert the original `state`/`clauses` are unchanged (AC-16 precondition) |
| `test_trail_validated_only` | `build_evidence_trail` emits rows only for validated findings with ≥1 snippet; discarded/`None` clauses contribute none (D5/AC-13) |
| `test_trail_row_shape_and_mapping` | Every row has exactly `{clause_id, evidence_source, evidence_text, retrieved_at}`; `evidence_source == snippet.source_reference`, `evidence_text == (truncated) snippet.snippet_text`, `clause_id ==` the clause key (AC-12/12a) |
| `test_trail_shared_timestamp` | All rows from one call share one `retrieved_at == generated_at` (D8/AC-12a) |
| `test_trail_empty_when_no_evidence` | Validated findings all without evidence → `build_evidence_trail` returns `[]` |

**Verify**: Run `python -m pytest tests/unit/test_report_assembler.py -v` — all 15 must FAIL (ImportError).

---

## Task 7: Implement `report_assembler.py` (`assemble_report` + `build_evidence_trail`)

- [ ] Create file `app/graph/nodes/renderers/report_assembler.py`
- [ ] **Imports**: `from typing import Any, Dict, List`; `from app.graph.state import ContractState, ValidationStatus, ClauseType, RiskLevel, RetrievalPath`; `from app.models.report import ContractReport, ReportFinding, ReportSummary, ReportEvidence`. **PURE — no file I/O, no `ollama`, no `app.config`** (limits are passed in as args).
- [ ] Define a module-level sentinel to distinguish "key absent" from "value None":

```python
_MISSING = object()
```

- [ ] **`assemble_report(state, generated_at, evidence_text_max_chars) -> ContractReport`** — pure state→model transform:
  - `document_id`, `original_filename`, `uploaded_at`, `processing_started_at`, `ocr_used`, `ocr_confidence` read from `state` (with sensible defaults).
  - **`ingest_error` set** → return a `ContractReport` with `ingest_error` populated, `findings == []`, and a zeroed `ReportSummary(total_clauses=0, validated_findings=0, clean_clauses=0, high=0, medium=0, low=0)` (Edge Case 1 / AC-20). Do not iterate clauses.
  - Otherwise: `clauses = state.get("clauses", {})`; `total_clauses = len(clauses)`.
  - **Findings** = records with `final_status == ValidationStatus.VALIDATED`, sorted by `record.get("position", 0)` (AC-1/2). For each, build a `ReportFinding`:
    - `risk_level` / `clause_type` / `path_taken` normalized to their `.value` via a helper `_enum_value(raw)` that returns `raw.value` for an Enum, `raw` for a str, else `None` (robust to enum **or** str after a checkpoint round-trip — AC / `test_enum_or_str_risk_level`).
    - **`rewrite_state`** derived once from `record.get("suggested_rewrite", _MISSING)`: `_MISSING` → `"not_eligible"`; `None` → `"unavailable"`; non-empty str → `"rewritten"` (spec AC-8). `suggested_rewrite` on the model is set only for `"rewritten"`.
    - `evidence` = each snippet mapped to `ReportEvidence(source_reference=..., snippet_text=...[:evidence_text_max_chars])`; a missing `snippet_text` / `source_reference` → a defined placeholder string (Edge Case 7). `evidence_snippets` `[]`/`None` → `[]`.
    - `confidence_score` passed through (`Optional[float]`).
  - `validated_findings = len(findings)`; `clean_clauses = total_clauses - validated_findings` (D4); H/M/L counts from the findings' normalized `risk_level`.
  - Return `ContractReport(..., generated_at=generated_at, summary=..., findings=..., node_timings=state.get("node_timings", {}), error_count=state.get("error_count", 0))`.
  - **Never mutates `state`** — read-only access; build new dicts/lists (AC-16).
- [ ] **`build_evidence_trail(report, generated_at) -> List[Dict[str, Any]]`** — flatten the ALREADY-assembled model's validated findings (single source of truth for D5 scope):

```python
def build_evidence_trail(report, generated_at):
    rows = []
    for f in report.findings:                 # already validated-only, ordered
        for ev in f.evidence:
            rows.append({
                "clause_id": f.clause_id,
                "evidence_source": ev.source_reference,
                "evidence_text": ev.snippet_text,     # already truncated by assemble_report
                "retrieved_at": generated_at,         # D8 — shared timestamp
            })
    return rows
```

**Verify**: Run `python -m pytest tests/unit/test_report_assembler.py -v` — all 15 must PASS.

---

## Task 8: Write unit tests for `render_markdown` (confirm FAILING)

- [ ] Create file `tests/unit/test_report_renderer.py`
- [ ] The import `from app.graph.nodes.renderers.markdown_renderer import render_markdown` will fail until Task 9 — expected for TDD.
- [ ] Pure string assertions over `ContractReport`s built directly (or via `assemble_report` on a fixture state). Write these 14 test functions (plan §2 renderer matrix, incl. the review-item-1 total-elapsed test):

| Test function | Verifies |
|---------------|----------|
| `test_header_counts_rendered` | Headline shows validated count + H/M/L + clean count (AC-9/D4) |
| `test_findings_in_position_order` | Finding sections appear in ascending `position` (AC-2) |
| `test_finding_shows_severity_and_rationale` | Each finding renders `risk_level` + `risk_rationale` (AC-3) |
| `test_finding_shows_text_and_locator` | `clause_text` + `section_number` (or `"§ n/a"` placeholder when `None`) shown (AC-4) |
| `test_provenance_rendered` | `path_taken` + `confidence_score` shown; graceful when either is `None` (AC-5) |
| `test_evidence_block_rendered` | Each snippet's `snippet_text` + `source_reference` shown; block omitted when `evidence == []` (AC-6/7) |
| `test_rewrite_three_states_distinct` | `"rewritten"` shows the rewrite text; `"unavailable"` shows the "_no rewrite available_" marker; `"not_eligible"` shows neither — all three distinguishable (AC-8) |
| `test_severity_unavailable_placeholder` | `risk_level is None` finding renders "severity unavailable", no crash (Edge Case 4) |
| `test_clean_clauses_counted_not_listed` | The clean count appears; no clean-clause text is enumerated (D4) |
| `test_ocr_caveat_when_ocr_used` | `ocr_used == True` → an OCR caveat line in the header (Edge Case 8); absent when `False` |
| `test_zero_findings_clean_report` | Zero validated findings → a well-formed "no findings" body, non-empty string (AC-18) |
| `test_ingest_error_minimal_body` | `report.ingest_error` set → a "could not be processed" header echoing the error message, no findings section (AC-20) |
| `test_footer_renders_partial_timings` | Missing/partial `node_timings` / `error_count` render without crash (Edge Case 10) |
| `test_footer_renders_total_elapsed` | Footer shows a total-elapsed line computed from `generated_at − processing_started_at`; renders `"unknown"` when `processing_started_at` is `None` (spec §2.3 item 4, **review item 1**) |

- [ ] `render_markdown` returns a `str` — assert on substring membership, not exact layout, so wording stays tunable.

**Verify**: Run `python -m pytest tests/unit/test_report_renderer.py -v` — all 14 must FAIL (ImportError).

---

## Task 9: Implement `markdown_renderer.py`

- [ ] Create file `app/graph/nodes/renderers/markdown_renderer.py`
- [ ] **Imports**: `from datetime import datetime`; `from app.models.report import ContractReport`. **PURE — string in, string out, no I/O.** Never raises on a `None` field (render a defined placeholder).
- [ ] **`render_markdown(report: ContractReport) -> str`** — layout per plan §2 / spec §2.3:
  1. **Header** — `original_filename`, `document_id`, `uploaded_at`, `processing_started_at`; an **OCR caveat** line when `report.ocr_used` (Edge Case 8); the headline count from `report.summary` (`"N clauses reviewed · F findings (H high / M medium / L low) · C clean"` — D4/AC-9). If `report.ingest_error` is set: render a "document could not be processed" header echoing the error message, then RETURN (skip findings — Edge Case 1 / AC-20).
  2. **Findings** — one `##` section per finding in `position` order: locator (`section_number` or `"§ n/a"`), `clause_type` (or "uncategorized"), `risk_level` (or "severity unavailable" — Edge Case 4), `risk_rationale`, the original `clause_text`, provenance (`path_taken` + `confidence_score` when present — AC-5), and an evidence block (omit when `evidence == []` — AC-7). `suggested_rewrite` rendered per `rewrite_state` (AC-8): `"rewritten"` → the rewrite; `"unavailable"` → `_no rewrite available_`; `"not_eligible"` → nothing.
  3. **Clean-clause summary** — a single count line from `report.summary.clean_clauses` (D4) — never an enumeration.
  4. **Processing footer** — per-**upstream**-node `node_timings` + `error_count` (render whatever is present — Edge Case 10) **and a total-elapsed line** computed from `report.generated_at − report.processing_started_at` (parse both ISO with `datetime.fromisoformat`; render `"unknown"` if `processing_started_at` is `None` or unparsable) — **review item 1 / spec §2.3 item 4**.
- [ ] **Accepted limitations (document both in a code comment; neither is a defect):**
  - (a) *Self-timing:* the report's own `node_timings["report"]` cannot appear in this footer because the node measures its `elapsed` AFTER `render_markdown` returns; the footer shows upstream timings + the computed total-elapsed line. `node_timings["report"]` lives only in `ContractState`. Inherent to a node rendering itself — do not try to "fix" it by threading a placeholder timing in.
  - (b) *Footer `error_count`:* the rendered footer's `error_count` reflects only **upstream** errors, because the report body is serialized BEFORE the write attempt — a write failure (which sets `error_count: 1` in state, AC-19) cannot appear inside a file that failed to write. This is inherent and expected; the write-failure health signal lives in `ContractState.error_count`, not in the report file.

**Verify**: Run `python -m pytest tests/unit/test_report_renderer.py -v` — all 14 must PASS. Then complete Task 5's re-exports and run `python -c "import app.graph.nodes.renderers; print('ok')"`.

---

## Task 10: Write unit tests for `report_agent` (confirm FAILING)

- [ ] Create file `tests/unit/test_report_agent.py`
- [ ] The import `from app.graph.nodes.report_agent import report_agent` will fail until Task 11 — expected for TDD.
- [ ] **No LLM mock anywhere** (D3). Real (pure) renderers, real temp-dir I/O. Monkeypatch `REPORT_OUTPUT_DIR` on the node module to `str(tmp_path)` so files land in pytest's `tmp_path`. Helper `make_state(...)` returning a state dict with `document_id`, `original_filename`, `uploaded_at`, `processing_started_at`, a `clauses` dict, `node_timings`, `error_count`.
- [ ] Write these 16 test functions (plan §2 node matrix, incl. the review-item-2 trail-on-failure test):

| Test function | Verifies |
|---------------|----------|
| `test_writes_md_and_json_pair` | Both files exist at the configured stem; the JSON deserializes; its `len(findings)` == the Markdown headline finding count (AC-17a / D1) |
| `test_report_path_points_at_existing_nonempty_md` | `report_path` → an existing, non-empty `.md` file (AC-10) |
| `test_report_body_not_in_state` | The return carries a `report_path` **string**, not the report body text (AC-11, constitution §6) |
| `test_evidence_trail_in_return` | `evidence_trail` present; rows validated-only; correct shape + mapping (AC-12/12a/13) |
| `test_current_node_pinned` | `current_node == "report"` and the same string is the key in the returned `node_timings` (AC-14) |
| `test_partial_update_only` | On success the return keys are exactly `{report_path, evidence_trail, current_node, node_timings}` — assert **no** `processing_completed_at` (D2), **no** `clauses`, **no** `error_count` (AC-15) |
| `test_clauses_not_mutated` | Deep-copy the input `clauses`; after the run the input dict is byte-for-byte unchanged (AC-16) |
| `test_paths_from_config` | Monkeypatch the output dir + both filename templates on the node module → files land at the monkeypatched location; nothing hardcoded (AC-17) |
| `test_zero_findings_writes_clean_report` | All-discarded `clauses` → files written, `report_path` set, no `error_count`, "no findings" body (AC-18) |
| `test_ingest_error_minimal_report` | `ingest_error` set → minimal report written, `report_path` set, no crash (AC-20) |
| `test_empty_clauses_writes_and_warns` | `clauses == {}` (no `ingest_error`) → a valid "no findings" report + a warning logged (AC-21); use `caplog` |
| `test_write_failure_emits_error_count` | Injected `OSError` on write → `report_path is None`, `error_count == 1`, no crash (AC-19, Edge Case 3) |
| `test_partial_pair_failure_cleans_orphan_json` | JSON write succeeds but Markdown write raises → the orphan JSON is removed, `report_path is None`, `error_count == 1` (AC-19a) |
| `test_json_written_before_markdown` | Assert write order (e.g. a `Path.write_text` spy records call order) so JSON precedes Markdown (AC-19a) |
| `test_write_failure_still_emits_trail` | On an injected write failure the return still contains the computed `evidence_trail` (deliberate — **review item 2**) |
| `test_rerun_overwrites_in_place` | Running the node twice on the same `document_id` overwrites the same `.md`/`.json` paths (not a second file); `report_path` unchanged across runs (D6 / Edge Case 9) |
| `test_no_llm_imported` | The `report_agent` module references no `ollama` and no model constant (D3) — e.g. assert `"ollama" not in sys.modules_referenced` via inspecting the module source or `importlib`; simplest: assert `not hasattr(app.graph.nodes.report_agent, "OLLAMA_MODEL_NAME")` |

- [ ] **Injecting a write failure** (`test_write_failure_emits_error_count`, `test_partial_pair_failure_cleans_orphan_json`): monkeypatch `pathlib.Path.write_text` (or the node's write helper) to raise `OSError` — either unconditionally (full failure) or only for the `.md` path (partial-pair). Assert `report_path is None` and `error_count == 1`; for the partial-pair case also assert the `.json` file no longer exists after the call.
- [ ] For `test_json_written_before_markdown`: record the sequence of written paths (e.g. append to a list in the monkeypatched `write_text`) and assert the `.json` path appears before the `.md` path.
- [ ] For `test_partial_update_only`: assert forbidden keys absent — `processing_completed_at`, `clauses`, `error_count`, `document_id`, `mcp_delivery_status`, `retry_budgets` (on a successful run).
- [ ] For `test_rerun_overwrites_in_place`: call `report_agent(state)` twice with the same `document_id`; assert `os.listdir(tmp_path)` contains exactly the one `.md` + one `.json` (no duplicates/timestamps), and both runs return the same `report_path` (D6 / Edge Case 9).

**Verify**: Run `python -m pytest tests/unit/test_report_agent.py -v` — all 17 must FAIL (ImportError).

---

## Task 11: Implement `report_agent.py`


- [ ] Create file `app/graph/nodes/report_agent.py`
- [ ] **Imports**: `time`, `logging`, `from datetime import datetime, timezone`, `from pathlib import Path` (stdlib); `from pydantic import ValidationError`; `from app.graph.state import ContractState`; `from app.graph.nodes.renderers import assemble_report, build_evidence_trail, render_markdown`. **No `ollama`, no model constant** (D3).
- [ ] **CRITICAL — config import pattern (mirror `risk_score_agent.py:42-49`)**: `import app.config as _config` and re-expose each tunable as a monkeypatchable module-level name read by **bare name**:

```python
import app.config as _config

REPORT_OUTPUT_DIR = _config.REPORT_OUTPUT_DIR
REPORT_MD_FILENAME_TEMPLATE = _config.REPORT_MD_FILENAME_TEMPLATE
REPORT_JSON_FILENAME_TEMPLATE = _config.REPORT_JSON_FILENAME_TEMPLATE
REPORT_EVIDENCE_TEXT_MAX_CHARS = _config.REPORT_EVIDENCE_TEXT_MAX_CHARS
```

- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.report")`
- [ ] Public interface:

```python
def report_agent(state: ContractState) -> dict:
    """LangGraph Node 7 (ReportAgent), the terminal node. Assembles a Pydantic report
    from ContractState, writes a Markdown report + JSON sibling under
    REPORT_OUTPUT_DIR, and returns a partial dict: report_path, evidence_trail,
    current_node, node_timings — plus error_count:1 ONLY when the file write fails.
    Makes NO LLM call. Never writes processing_completed_at (runner-owned, D2)."""
```

- [ ] **Internal flow** (plan §2 — follow exactly):
  1. `start_time = time.monotonic()`; `current_node = "report"`; `document_id = state.get("document_id", "unknown")`; `generated_at = datetime.now(timezone.utc).isoformat()` (**the one D8 timestamp** — reuse for every trail row).
  2. `report_model = assemble_report(state, generated_at, REPORT_EVIDENCE_TEXT_MAX_CHARS)`; `evidence_trail = build_evidence_trail(report_model, generated_at)`. (Both pure; on `ingest_error`, `assemble_report` returns the minimal report — Edge Case 1.)
  3. `md_text = render_markdown(report_model)`; `json_text = report_model.model_dump_json(indent=2)`.
  4. Resolve paths: `out_dir = Path(REPORT_OUTPUT_DIR)`; `json_path = out_dir / REPORT_JSON_FILENAME_TEMPLATE.format(document_id=document_id)`; `md_path = out_dir / REPORT_MD_FILENAME_TEMPLATE.format(document_id=document_id)`.
  5. **Write inside one `try`** (see failure path): `out_dir.mkdir(parents=True, exist_ok=True)`; **write `json_path` FIRST**, then `md_path` (AC-19a); `report_path = str(md_path)`.
  6. `elapsed = time.monotonic() - start_time`.
  7. Aggregate metrics log (spec §9): `logger.info("ReportAgent completed", extra={"total_clauses": report_model.summary.total_clauses, "validated_findings": report_model.summary.validated_findings, "clean_clauses": report_model.summary.clean_clauses, "high": report_model.summary.high, "medium": report_model.summary.medium, "low": report_model.summary.low, "evidence_rows": len(evidence_trail), "report_chars": len(md_text), "write_ok": True, "elapsed_seconds": round(elapsed, 4)})`.
  8. Return `{"report_path": report_path, "evidence_trail": evidence_trail, "current_node": current_node, "node_timings": {current_node: elapsed}}` — **no** `processing_completed_at`, **no** `clauses`, **no** `error_count`.
- [ ] **Failure path** (`except (OSError, ValidationError) as exc:`) — spec §2.2 / §7.6 / AC-19 / AC-19a:
  - `logger.error("ReportAgent: failed to write report for document_id=%s: %s", document_id, exc)`.
  - `_cleanup_orphan(json_path, md_path)` — if `json_path` exists but `md_path` does not, `json_path.unlink()` (best-effort; swallow its own `OSError`), log a debug line. So state never implies a pair that isn't consistent (AC-19a).
  - `elapsed = time.monotonic() - start_time`.
  - Return `{"report_path": None, "evidence_trail": evidence_trail, "current_node": current_node, "node_timings": {current_node: elapsed}, "error_count": 1}`. **`evidence_trail` is emitted even here — deliberate (review item 2):** it is computed pre-write from in-memory state and is valid regardless of the disk write; locked by `test_write_failure_still_emits_trail`.
- [ ] **Key invariants** (make them hold by construction):
  - `report_path` is a real, existing, non-empty `.md` file on success; `None` on write failure (AC-10/11/19). Always a path string, never the body (AC-11).
  - JSON is written before Markdown; a mid-pair failure leaves no orphan the state points at (AC-19a).
  - `clauses` is never in the return and is never mutated (AC-16).
  - `processing_completed_at` is never in the return (D2 / AC-15).
  - `error_count` appears iff — and exactly once when — the write failed (AC-19).
  - No LLM call, ever (D3).
- [ ] **Pinned `current_node`**: the literal `"report"` (spec §7.5) — also the `node_timings` key and the graph node name in Task 12. Do NOT derive it.

**Verify**: Run `python -m pytest tests/unit/test_report_agent.py -v` — all 17 must PASS.

---

## Task 12: Wire the `report` node into the graph builder (fan-in)

- [ ] Open `app/graph/builder.py`
- [ ] Add the import: `from app.graph.nodes.report_agent import report_agent`
- [ ] **Replace** the two temporary placeholder edges (`builder.py:121-122`):

```python
    graph.add_edge("redline", END)        # → "report" once feature-009 (Node 7) exists
    graph.add_edge("skip_redline", END)   # → "report" once feature-009 (Node 7) exists
```

with the `report` node + fan-in + terminal edge:

```python
# ── Node 7: ReportAgent (terminal assembly node) ──────────────────────────────
# Constitution §2 item 7. Both Node-6 branches converge here via plain LINEAR
# add_edge (fan-in) — NOT a conditional edge — so the graph still has exactly the
# two permitted domain conditional edges (CRAG internal, route_on_risk). ReportAgent
# reads the fully-populated ContractState, writes the report file(s), and returns
# report_path + evidence_trail (spec §7.1). The node name "report" matches the pinned
# current_node value (spec §7.5) so state-key identity never drifts from the graph
# node name (constitution §8).
graph.add_node("report", report_agent)
graph.add_edge("redline", "report")        # was END (feature-008 placeholder)
graph.add_edge("skip_redline", "report")   # was END (feature-008 placeholder)
graph.add_edge("report", END)
```

- [ ] Update the module docstring "Current scope" note (`builder.py:4-11`) to include Node 7 and remove the two "→ END temporarily / → report once feature-009 exists" placeholder lines.
- [ ] Leave `route_after_ingest` (the ingest error-guard, `builder.py:46`) unchanged — it still short-circuits `ingest_error → END`, so `report` is **not** reached on an ingest error in the current graph (that is intentional; see the Task 13 note).

**Verify**: Run from `backend/`:
```
python -c "from app.graph.builder import build_graph; g = build_graph(); print(type(g))"
```
Should print the compiled graph type without errors.

---

## Task 13: Write and run integration tests

- [ ] Create file `tests/integration/test_report_graph.py`
- [ ] Tests exercise the compiled graph through Node 7. **No live Ollama:** monkeypatch `REPORT_OUTPUT_DIR` to `tmp_path`; mock the upstream LLM/embed/web boundaries (ClauseSplitter's `ollama.chat`, CRAG's `embed_query`/`web_search`, Self-RAG's reflectors, `risk_score_agent.score_risk`, `redline_agent.draft_rewrite`) as in the 005–008 integration tests (patch-where-bound — see `test_redline_graph.py`), OR inject a pre-built `clauses` fixture (with `final_status` + `risk_level` set) and run from a suitable entry point.
- [ ] Write these 8 test functions (plan §2 matrix):

| Test function | Verifies |
|---------------|----------|
| `test_graph_reaches_report_and_ends` | A doc with mixed validated/discarded clauses + ≥1 rewrite reaches `report`; final `current_node == "report"`; `report_path` exists on disk; terminates at END (AC-25) |
| `test_graph_redline_branch_fans_into_report` | An eligible-finding doc flows `redline → report` (not END); a report file is written (AC-22) |
| `test_graph_skip_redline_branch_fans_into_report` | An all-`DISCARDED` doc flows `skip_redline → report`; a report file is written; final `current_node == "report"` (AC-22) |
| `test_graph_report_to_end` | Inspect `build_graph().get_graph()`: `report`'s only successor is `END` (AC-23) |
| `test_graph_ingest_error_still_reaches_end` | An ingest error short-circuits to END **without** reaching `report` (the current wiring); assert `assert not final_state.get("clauses")` and that no `report_path` was produced. Documents that the node-level minimal-report behavior (AC-20) is what protects a future graph — see note below |
| `test_graph_no_new_conditional_edges` | `report` is reached only by linear edges from `redline`/`skip_redline`; conditional branch sources are exactly `{ingest_agent, risk_score}`; `crag_retrieval`/`self_rag_validation` stay linear (AC-24) |
| `test_graph_evidence_trail_populated` | After a full run, final `evidence_trail` has validated-only rows sharing the D8 timestamp, correct shape (AC-12a/13) |
| `test_graph_checkpointing_after_report` | State checkpointed after Node 7. Build the test's **own** graph with `SqliteSaver.from_conn_string(":memory:")` (wrapped `try/except ImportError → pytest.skip`) since `build_graph()` compiles with no checkpointer. The own subgraph MUST wire the tail end-to-end through `report` (`… → {redline, skip_redline} → report → END`), NOT copy 008's `→ END` verbatim; assert `compiled.get_state(thread_cfg)` is retrievable and its `current_node == "report"`. Mirrors `test_redline_graph.py` checkpointing |

- [ ] **Note on the ingest-error path (do NOT "fix" the guard):** `route_after_ingest` (`builder.py:46`) short-circuits `ingest_error → END`, so an ingest-errored run never reaches `report` in the current graph. The spec's Edge Case 1 / AC-20 (report writes a minimal report on `ingest_error`) is therefore exercised at the **node** level (`test_report_agent.py::test_ingest_error_minimal_report`), and is defensive at the graph level. `test_graph_ingest_error_still_reaches_end` asserts the *current* wiring; it must NOT modify the guard to force `report` on error — that would be a `builder.py` scope change beyond this feature.
- [ ] **KeyError caution** (`test_graph_ingest_error_still_reaches_end`): `clauses` is an `Annotated[dict, merge_nested_clause_dicts]` channel with no default; on the error short-circuit it is never written, so `final_state["clauses"]` raises `KeyError`. Assert `assert not final_state.get("clauses")` instead (same subtlety as 004–008).

**Verify**: Run `python -m pytest tests/integration/test_report_graph.py -v` — all 8 must PASS (checkpointing may skip if the SQLite saver import path is unavailable — acceptable).

---

## Task 14: Full test suite pass + terminal-node regression fix-ups

- [ ] Run the complete suite:
```
python -m pytest tests/ -v --tb=short
```
- [ ] All existing IngestAgent (003), ClauseSplitter (004), CRAG (005), Self-RAG (006), RiskScore (007), and Redline (008) unit tests must still pass — Node 7 must not regress them.
- [ ] **Regression caution — the tail edge moved AGAIN (read fully).** Feature-008 made `redline` / `skip_redline` terminal (`… → {redline, skip_redline} → END`). This feature moves the tail to `… → {redline, skip_redline} → report → END`. Every integration test that invokes the real `build_graph()` and runs to END currently asserts the terminal `current_node` is `"redline"` (or `"skip_redline"`). That assumption is now false — the terminal node is `"report"`. These failures are **EXPECTED and benign**: the graph still reaches END; the new `report` node makes **no** LLM call, so nothing new can fail against a mocked Ollama. Do **NOT** treat the red as a bug and do **NOT** weaken these assertions (constitution §7) — **update** each to the new terminal node `"report"`.
- [ ] **Grep first — do not trust line numbers (they drifted after 008).** Run:
  ```
  grep -rn "current_node.*\"redline\"\|current_node.*\"skip_redline\"\|== \"redline\"\|== \"skip_redline\"" tests/integration/
  ```
  For every assertion that checks the terminal `current_node` of a **full `build_graph()` run**, change the expected value to `"report"`. These are the same set feature-008 last touched, now one node further along:
  - `tests/integration/test_ingest_graph.py` (was `"redline"` → `"report"`; fix the accompanying comment)
  - `tests/integration/test_clause_splitter_graph.py` (two assertions → `"report"`; fix comments)
  - `tests/integration/test_crag_retrieval_graph.py` (→ `"report"`)
  - `tests/integration/test_self_rag_validation_graph.py` (the full-graph test → `"report"`)
  - `tests/integration/test_risk_score_graph.py` (the full-graph test → `"report"`)
  - `tests/integration/test_redline_graph.py` — the two routing tests that asserted `current_node == "redline"` / `"skip_redline"` on a full-graph run now assert `"report"`. Keep their **branch-evidence** assertions unchanged (an eligible clause still has a non-empty `suggested_rewrite`; an all-discarded doc still has none) — those prove which branch was taken; `current_node` proves the terminal node. `test_graph_circuit_open_sets_error_count` keeps asserting `error_count == 1` (now terminal at `report`, which does not clear it).
- [ ] **Do NOT change the self-contained subgraph/checkpointing tests** — they wire their own terminal edge and remain correct as-is:
  - `test_self_rag_validation_graph.py` checkpointing case (builds `self_rag_validation → END`).
  - `test_risk_score_graph.py` checkpointing case (builds `risk_score → END`).
  - `test_redline_graph.py` checkpointing case (builds its own tail to `redline`/`skip_redline` → END).
  These assert their own subgraph's terminal node, not the real `build_graph()` tail — leave them.
- [ ] After the updates, the only diffs in these files should be the terminal-node string (`"redline"`/`"skip_redline"` → `"report"`) and the accompanying comments. Re-run the full suite until green.
- [ ] Expected NEW test count for feature 009: 4 (config) + 5 (models) + 15 (assembler) + 14 (renderer) + 17 (node) + 8 (integration) = **63 new tests**.
- [ ] OCR-gated IngestAgent tests may skip if Tesseract is absent — acceptable. **No Report test requires Tesseract, a live Ollama, or the network** (Node 7 is deterministic, no LLM).

---

## Task 15: Linting and type checking

- [ ] Run `black app/ tests/` — auto-format.
- [ ] Run `ruff check app/ tests/` — no lint errors.
- [ ] Run `mypy app/` — no type errors (if mypy is installed). The Pydantic models in `app/models/report.py` are fully typed; add narrow `# type: ignore[...]` only if genuinely needed — do NOT broaden.
- [ ] Do NOT weaken tests to satisfy lint/type checks — fix the implementation instead (constitution §7).

---

## Task 16: Manual smoke test (optional, not in automated suite)

- [ ] **No Ollama needed for Node 7 itself** (deterministic — D3). A true end-to-end (Node 1→7) still needs Ollama for the upstream nodes; per project memory the dev box OOMs on live `qwen3:14b`, so this may not be runnable here. The automated suite (Task 14) is fully mocked and must pass regardless.
- [ ] If running E2E: process a real multi-clause contract and open the generated `data/reports/{document_id}.md` and `.json`. Confirm:
  - Only VALIDATED findings appear; discarded clauses are absent; clean clauses show as a count only (D4).
  - Each finding shows severity, rationale, original text, provenance, evidence, and a rewrite rendered per its three states (AC-8).
  - The header counts match the findings rendered; the footer shows upstream `node_timings` + a total-elapsed line; `report_path` points at the `.md`.
  - The `.json` deserializes and its `findings` count matches the `.md` headline.
- [ ] Record findings roll-up, redline coverage, and report size (spec §9) for later calibration of `REPORT_EVIDENCE_TEXT_MAX_CHARS`.

**Why**: The automated suite exercises the mechanics; this is the only step that eyeballs real report readability and the actual severity/evidence content.

---

## Summary of all files created/modified

| # | File | Action |
|---|------|--------|
| 1 | `app/config.py` | MODIFIED (add 4 Report constants — no new import) |
| 2 | `app/models/report.py` | NEW (Pydantic boundary models: `ContractReport`, `ReportFinding`, `ReportSummary`, `ReportEvidence`) |
| 3 | `app/graph/nodes/renderers/__init__.py` | NEW (package marker + re-exports) |
| 4 | `app/graph/nodes/renderers/report_assembler.py` | NEW (`assemble_report`, `build_evidence_trail`, `_enum_value`, `_MISSING`) |
| 5 | `app/graph/nodes/renderers/markdown_renderer.py` | NEW (`render_markdown`) |
| 6 | `app/graph/nodes/report_agent.py` | NEW (`report_agent`, `_cleanup_orphan`) |
| 7 | `app/graph/builder.py` | MODIFIED (add `report` node; rewire `redline`/`skip_redline` → `report`; `report → END`) |
| 8 | `tests/unit/test_config.py` | MODIFIED (+4 tests) |
| 9 | `tests/unit/test_report_models.py` | NEW (5 tests) |
| 10 | `tests/unit/test_report_assembler.py` | NEW (15 tests) |
| 11 | `tests/unit/test_report_renderer.py` | NEW (14 tests) |
| 12 | `tests/unit/test_report_agent.py` | NEW (16 tests) |
| 13 | `tests/integration/test_report_graph.py` | NEW (8 tests) |
| 14 | `tests/integration/test_ingest_graph.py` | MODIFIED (Task 14 regression: terminal-node `"redline"` → `"report"` + comment) |
| 15 | `tests/integration/test_clause_splitter_graph.py` | MODIFIED (Task 14 regression: two terminal-node assertions → `"report"` + comments) |
| 16 | `tests/integration/test_crag_retrieval_graph.py` | MODIFIED (Task 14 regression: terminal-node → `"report"`) |
| 17 | `tests/integration/test_self_rag_validation_graph.py` | MODIFIED (Task 14 regression: full-graph test → `"report"`; NOT the checkpointing case) |
| 18 | `tests/integration/test_risk_score_graph.py` | MODIFIED (Task 14 regression: full-graph test → `"report"`; NOT the checkpointing case) |
| 19 | `tests/integration/test_redline_graph.py` | MODIFIED (Task 14 regression: two routing tests' terminal `current_node` → `"report"`; NOT the checkpointing case) |

> Files 14–19 are **expected regression fix-ups**, not new feature code — the tail edge moving from `… → {redline, skip_redline} → END` to `… → {redline, skip_redline} → report → END` invalidates the "redline/skip_redline is terminal" assertion (see Task 14). Grep and update; do not weaken.

---

## Acceptance-criteria traceability (spec §3 → tasks)

| Spec §3 criterion | Covered by |
|-------------------|-----------|
| **Report assembly** | |
| 1. Only validated clauses become findings | Task 6/7 (`test_only_validated_become_findings`) |
| 2. Findings ordered by `position` | Task 6/7 (`test_findings_ordered_by_position`), Task 8/9 (`test_findings_in_position_order`) |
| 3. Each finding renders severity + rationale | Task 8/9 (`test_finding_shows_severity_and_rationale`) |
| 4. Original text + locator | Task 8/9 (`test_finding_shows_text_and_locator`) |
| 5. Provenance shown | Task 8/9 (`test_provenance_rendered`) |
| 6. Evidence snippets rendered | Task 8/9 (`test_evidence_block_rendered`) |
| 7. Empty-evidence finding still renders | Task 6/7 (`test_empty_evidence_finding`), Task 8/9 (`test_evidence_block_rendered`) |
| 8. `suggested_rewrite` three states distinct | Task 6/7 (`test_rewrite_state_three_way`), Task 8/9 (`test_rewrite_three_states_distinct`) |
| 9. Header counts correct | Task 6/7 (`test_summary_counts_correct`), Task 8/9 (`test_header_counts_rendered`) |
| **State outputs** | |
| 10. `report_path` → existing non-empty file | Task 10/11 (`test_report_path_points_at_existing_nonempty_md`) |
| 11. Report body NOT in state | Task 10/11 (`test_report_body_not_in_state`) |
| 12. `evidence_trail` fixed row shape | Task 6/7 (`test_trail_row_shape_and_mapping`), Task 10/11 (`test_evidence_trail_in_return`) |
| 12a. Row-field mapping correct (D8) | Task 6/7 (`test_trail_row_shape_and_mapping`, `test_trail_shared_timestamp`) |
| 13. `evidence_trail` scope | Task 6/7 (`test_trail_validated_only`, `test_trail_empty_when_no_evidence`), Task 13 (`test_graph_evidence_trail_populated`) |
| 14. `current_node` pinned | Task 10/11 (`test_current_node_pinned`) |
| 15. Partial update only | Task 10/11 (`test_partial_update_only`) |
| 16. Clauses not mutated | Task 6/7 (`test_assembler_does_not_mutate_state`), Task 10/11 (`test_clauses_not_mutated`) |
| 17. Output path/filenames from config | Task 1 (`test_report_constants_match_spec`), Task 10/11 (`test_paths_from_config`) |
| 17a. Markdown + JSON pair written | Task 10/11 (`test_writes_md_and_json_pair`) |
| **Degenerate & failure paths** | |
| 18. Zero validated → clean report | Task 8/9 (`test_zero_findings_clean_report`), Task 10/11 (`test_zero_findings_writes_clean_report`) |
| 19. Report-file write failure | Task 10/11 (`test_write_failure_emits_error_count`, `test_write_failure_still_emits_trail`) |
| 19a. Partial MD/JSON pair failure | Task 10/11 (`test_partial_pair_failure_cleans_orphan_json`, `test_json_written_before_markdown`) |
| 20. `ingest_error` → minimal report | Task 6/7 (`test_ingest_error_minimal_report`), Task 8/9 (`test_ingest_error_minimal_body`), Task 10/11 (`test_ingest_error_minimal_report`) |
| 21. Empty `clauses` (no ingest_error) | Task 10/11 (`test_empty_clauses_writes_and_warns`) |
| EC9. Re-run overwrites in place | Task 1 (`test_report_filename_templates_have_document_id`), Task 10/11 (`test_rerun_overwrites_in_place`) |
| **Graph wiring** | |
| 22. `report` registered + fan-in wired | Task 12, Task 13 (`test_graph_redline_branch_fans_into_report`, `test_graph_skip_redline_branch_fans_into_report`) |
| 23. `report → END` | Task 12, Task 13 (`test_graph_report_to_end`) |
| 24. No new conditional edge | Task 13 (`test_graph_no_new_conditional_edges`) |
| 25. Whole-graph smoke | Task 13 (`test_graph_reaches_report_and_ends`) |
| **Review items (spec §2.3 / plan)** | |
| Total-elapsed footer line (§2.3 item 4) | Task 8/9 (`test_footer_renders_total_elapsed`) |
| Trail emitted on write failure (deliberate) | Task 10/11 (`test_write_failure_still_emits_trail`) |
| Self-timing footer limitation (accepted) | Task 9 (code comment; no test — inherent, non-defect) |
| Footer `error_count` = upstream-only (accepted) | Task 9 (code comment; no test — inherent, non-defect) |
```
