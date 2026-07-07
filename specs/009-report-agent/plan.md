
# ReportAgent Technical Plan

## Git Branch

`feature/009-report-agent` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement **Node 7 (ReportAgent)** as specified in
`specs/009-report-agent/spec.md`. Node 7 is the **terminal** node of the fixed
7-node pipeline and the pipeline's single **presentation-assembly** stage. It is
structurally the simplest generative-era node because it makes **no LLM call, no
retrieval, no routing decision, and runs no circuit breaker** (spec §7.2, D3) — it
is a deterministic function of the fully-populated `ContractState` plus one file
write.

It owns **one graph node** (`report`) and the **fan-in rewiring** of the two
feature-008 placeholder edges:

1. **ReportAgent** (`report` node) — reads the accumulated `ContractState`,
   assembles an in-memory **Pydantic** report model from the `VALIDATED` findings,
   serializes it to **two files** — a human-readable Markdown report and a
   machine-readable JSON sibling (D1) — under `REPORT_OUTPUT_DIR`, and returns
   `report_path` + `evidence_trail` (+ `current_node` / `node_timings`, + a single
   `error_count: 1` health signal iff the file write fails).
2. **Graph rewiring** — `builder.py` replaces the two temporary `redline → END` /
   `skip_redline → END` placeholders (`builder.py:121-122`) with
   `redline → report` and `skip_redline → report`, then adds `report → END`. This
   is a plain **linear fan-in** (two `add_edge`s into one node) — it introduces
   **zero** new conditional edges, preserving constitution §2's "exactly 2
   conditional edges" invariant (spec §7.1, AC-22/23/24).

The node writes only `report_path`, `evidence_trail`, `current_node`, and
`node_timings`, per the partial-update rule (constitution §5). The **one**
exception is the write-failure health signal: a single `error_count: 1` when the
report file cannot be persisted (spec §2.2 / §7.6, AC-19). It **never** writes
`processing_completed_at` (D2 — runner-owned), never mutates `clauses`, and never
touches any key owned by Nodes 1–6.

**Resolved design decisions carried from the spec (§8a D1–D8):**
- **D1 — Markdown body + sibling JSON.** Both are dependency-free (no HTML/PDF
  renderer exists in `002-tech-stack.md`). `report_path` points at the Markdown
  file (the canonical human deliverable); the JSON sibling shares the same stem.
- **D2 — the graph runner, not ReportAgent, stamps `processing_completed_at`.**
  Symmetric with `processing_started_at` (pipeline-level, node-agnostic). The node's
  partial update never contains it. **Integration caveat carried to §6:** no runner
  currently stamps it, so it is presently written by nobody — an out-of-scope
  Phase-1 gap owned by the future runner/API feature.
- **D3 — no LLM executive summary in Phase 1.** The node is fully deterministic —
  zero LLM calls, no timeout / circuit-breaker / model constant (contrast Nodes 3–6).
- **D4 — clean (non-validated) clauses are counted, not enumerated.** The header
  shows an aggregate ("N clauses reviewed · F findings · C clean"); listing clean
  clauses risks re-surfacing `DISCARDED` content that constitution §2.4 says is
  never shown.
- **D5 — `evidence_trail` covers validated findings only,** one row per
  (validated finding, supporting snippet).
- **D6 — deterministic filenames `{document_id}.md` / `.json` under
  `data/reports/`;** a re-run overwrites in place. History/retention is Phase-2.
- **D7 — MCP Drive/Gmail delivery is a separate future feature (`specs/010-*`),**
  out of scope. Node 7 ends at "report on disk + `report_path`/`evidence_trail` in
  state".
- **D8 — `evidence_trail.retrieved_at` = one report-generation ISO timestamp**
  (`datetime.now(timezone.utc)`, taken once at node start, shared by all rows). CRAG
  persists no per-snippet retrieval time (`make_snippet()`,
  `retrievers/__init__.py:34`, produces exactly `{snippet_text, source_reference}`),
  so this spec narrows `001` §3's "when retrieved/validated" gloss to "when the
  trail row was compiled" for Phase 1 — a documentation-only narrowing, no schema
  change.

**Boundary Pydantic model (constitution §4).** Writing the report to disk is a
system-boundary crossing, so the report structure is a **Pydantic** model
(`app/models/report.py`), built *from* the TypedDict `ContractState` and validated
before serialization. The Pydantic model is a serialization type only — it is never
stored in graph state, keeping the §4 TypedDict/Pydantic separation intact.

**State minimality (constitution §6).** The rendered report can be large (every
finding, its evidence, its rewrite), so the body goes to files and only
`report_path` (a string) enters state. The only report-derived content that lives in
state is the bounded `evidence_trail`, whose per-row `evidence_text` is truncated to
`REPORT_EVIDENCE_TEXT_MAX_CHARS`.

---

## 2. Files to Create / Modify

### Shared Config Module

#### [MODIFY] `backend/app/config.py`

Add a new `# ── Report thresholds` block (no Report constant exists yet — pure
addition, no rename). All values are plain `str` / `int`, so **no new import** is
needed (the existing `from app.graph.state import RiskLevel` at `config.py:11` is
untouched — Report needs no enum).

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

There is intentionally **no** LLM / timeout / circuit-breaker / model constant —
the node makes no LLM call (D3). There is no retry constant (a file-write failure
takes the fail-safe health signal, not a retry loop).

---

### Boundary Pydantic Model

New module `backend/app/models/report.py`. `app/models/` currently holds only
`.gitkeep` — it is the designated home for boundary Pydantic models (constitution
§4), distinct from the TypedDict graph state in `app/graph/state.py`. These models
are the serialized report's schema; the JSON output is literally
`ContractReport.model_dump_json(...)`, and the Markdown renderer walks the same
model, so the two output formats can never structurally drift (D1).

#### [NEW] `backend/app/models/report.py`

```python
from typing import List, Optional
from pydantic import BaseModel, Field

class ReportEvidence(BaseModel):
    """One evidence snippet behind a finding (001 snippet shape, source_reference +
    snippet_text). Text is already truncated by the assembler to
    REPORT_EVIDENCE_TEXT_MAX_CHARS before model construction."""
    source_reference: str
    snippet_text: str

class ReportFinding(BaseModel):
    """One VALIDATED clause rendered as a finding (spec §2.3 item 2)."""
    clause_id: str
    position: int
    section_number: Optional[str] = None
    clause_type: Optional[str] = None          # ClauseType.value, or None
    risk_level: Optional[str] = None           # RiskLevel.value; None → "severity unavailable" (Edge Case 4)
    risk_rationale: Optional[str] = None
    clause_text: str
    # Three-state suggested_rewrite (feature-008 §2.2), pre-flattened by the assembler:
    #   rewrite_state ∈ {"rewritten", "unavailable", "not_eligible"}
    rewrite_state: str
    suggested_rewrite: Optional[str] = None    # present only when rewrite_state == "rewritten"
    path_taken: Optional[str] = None           # RetrievalPath.value, or None
    confidence_score: Optional[float] = None
    evidence: List[ReportEvidence] = Field(default_factory=list)

class ReportSummary(BaseModel):
    """Header roll-up counts (D4 — clean clauses counted, not enumerated)."""
    total_clauses: int
    validated_findings: int
    clean_clauses: int          # non-validated (discarded / None) — count only (D4)
    high: int
    medium: int
    low: int

class ContractReport(BaseModel):
    """The whole serialized report. Built from ContractState; never stored in state."""
    document_id: str
    original_filename: str
    uploaded_at: str
    processing_started_at: Optional[str] = None
    generated_at: str                          # the D8 report-generation timestamp
    ocr_used: bool = False
    ocr_confidence: Optional[float] = None
    ingest_error: Optional[dict] = None        # set → minimal "could not process" report (Edge Case 1)
    summary: ReportSummary
    findings: List[ReportFinding] = Field(default_factory=list)   # ordered by position
    node_timings: dict = Field(default_factory=dict)
    error_count: int = 0
```

Notes:
- The assembler **flattens** the three-state `suggested_rewrite` into an explicit
  `rewrite_state` label so both renderers (and any future JSON consumer) don't each
  re-derive "absent vs None vs str" from raw state — that logic lives in **one**
  place (the assembler), matching feature-008 §2.2's three states (spec AC-8).
- Pydantic validates types at construction; a malformed finding (e.g. missing
  `clause_text`) raises at assembly time inside the node's `try` (→ Edge Case 3
  path), never mid-serialization.

---

### Renderer Package

New package `backend/app/graph/nodes/renderers/`, following the sub-package
precedent of `scorers/` (Node 5), `drafters/` (Node 6), `validators/` (Node 4),
`retrievers/` (Node 3): a package `__init__.py` plus focused, independently testable
modules. The assembly and Markdown rendering are **pure functions** (no I/O, no
state mutation) so they are fully deterministic under test without any mock.

#### [NEW] `backend/app/graph/nodes/renderers/__init__.py`

Package marker with a module docstring. Re-exports `assemble_report`,
`build_evidence_trail`, and `render_markdown` for a clean import surface from the
node.

#### [NEW] `backend/app/graph/nodes/renderers/report_assembler.py`

The pure state→model transform. **No file I/O, no LLM, never mutates `state`.**

```python
def assemble_report(state: ContractState, generated_at: str,
                    evidence_text_max_chars: int) -> ContractReport:
    """Build the ContractReport from ContractState. Pure — reads state, returns a
    validated Pydantic model. Findings = VALIDATED clauses only (spec §2.4, D5),
    ordered by `position`. Clean clauses are counted, not enumerated (D4). On
    ingest_error, returns a minimal report (empty findings, ingest_error populated)
    — Edge Case 1. generated_at is the shared D8 timestamp."""
```

Behavior:
- `ingest_error` set → return a `ContractReport` with `ingest_error` populated,
  `findings == []`, and a zeroed `ReportSummary` (Edge Case 1 / AC-20).
- Otherwise iterate `clauses`:
  - `total_clauses = len(clauses)`.
  - **Findings** = records with `final_status == ValidationStatus.VALIDATED`, sorted
    by `position` (AC-1/2). Each maps to a `ReportFinding`:
    - `risk_level` / `clause_type` / `path_taken` normalized to their `.value`
      (robust to enum **or** str after a checkpoint round-trip — same str-Enum
      hash-equality Node 6 relies on); `None` preserved.
    - `rewrite_state` derived once from the three-state `suggested_rewrite`
      (feature-008 §2.2): key **absent** → `"not_eligible"`; value `None` →
      `"unavailable"`; non-empty `str` → `"rewritten"` (spec AC-8). Uses a sentinel
      to distinguish "key absent" from "value None" (`record.get("suggested_rewrite", _MISSING)`).
    - `evidence` = each snippet mapped to `ReportEvidence`, `snippet_text` truncated
      to `evidence_text_max_chars`; missing `snippet_text`/`source_reference` →
      a defined placeholder (Edge Case 7). Empty/`None` `evidence_snippets` → `[]`
      (Edge Case / AC-7).
  - `clean_clauses = total_clauses - validated_findings` (D4).
  - `ReportSummary` H/M/L counts from the findings' `risk_level`.
- Never raises on a `None` field (renders placeholders); only a genuinely malformed
  record (wrong *type* where Pydantic requires one) surfaces as a validation error,
  caught by the node.

#### [NEW] `backend/app/graph/nodes/renderers/report_assembler.py` — `build_evidence_trail`

Colocated with the assembler (same walk over validated findings, single source of
truth for D5 scope):

```python
def build_evidence_trail(report: ContractReport, generated_at: str) -> List[Dict[str, Any]]:
    """Flatten the report's validated findings into 001-shaped evidence_trail rows
    (spec §2.2, D5). One row per (finding, evidence snippet). retrieved_at =
    generated_at for every row (D8). Returns [] when no finding has evidence."""
    rows = []
    for f in report.findings:                 # already validated-only, ordered
        for ev in f.evidence:
            rows.append({
                "clause_id": f.clause_id,               # AC-12a
                "evidence_source": ev.source_reference, # AC-12a
                "evidence_text": ev.snippet_text,       # already truncated by assembler
                "retrieved_at": generated_at,           # D8 — shared timestamp
            })
    return rows
```

Building the trail from the **already-assembled model** (not from raw state) means
the trail and the rendered evidence are provably the same data (AC-13) and the D5
"validated-only" scope is enforced in exactly one place.

#### [NEW] `backend/app/graph/nodes/renderers/markdown_renderer.py`

```python
def render_markdown(report: ContractReport) -> str:
    """Render a ContractReport to a Markdown string. Pure — no I/O. Deterministic
    (stable section order = findings by position). Never raises on None fields
    (renders defined placeholders — Edge Case 4/7/10)."""
```

Layout (spec §2.3):
1. **Header** — `original_filename`, `document_id`, `uploaded_at`,
   `processing_started_at`; an **OCR caveat** line when `report.ocr_used`
   (Edge Case 8); the headline count from `ReportSummary`
   ("N clauses reviewed · F findings (H high / M medium / L low) · C clean" — D4/AC-9).
   On `ingest_error`, a "document could not be processed" header echoing the error
   message, then stop (Edge Case 1 / AC-20).
2. **Findings** — one `##` section per finding, in `position` order: locator
   (`section_number` or `"§ n/a"`), `clause_type`, `risk_level` (or
   "severity unavailable" — Edge Case 4), `risk_rationale`, original `clause_text`,
   provenance (`path_taken` + `confidence_score` when present — AC-5), and an
   evidence block (omitted when `evidence == []` — AC-7). `suggested_rewrite`
   rendered per `rewrite_state` (AC-8): `"rewritten"` → the rewrite; `"unavailable"`
   → a "_no rewrite available_" marker; `"not_eligible"` → neither (nothing shown).
3. **Clean-clause summary** — a single count line (D4) — never an enumeration.
4. **Processing footer** — `node_timings` per **upstream** node + `error_count`
   (Edge Case 10 — render whatever is present) **and a total-elapsed line** (spec
   §2.3 item 4). Total elapsed is computed from the model's own timestamps:
   `generated_at − processing_started_at` (both ISO; render `"unknown"` if
   `processing_started_at` is absent — see the D2 caveat). **Accepted limitation
   (review item 3):** the report's *own* `node_timings["report"]` cannot appear in
   its own footer because the node's `elapsed` is measured *after* `render_markdown`
   returns; the footer therefore shows the upstream nodes' timings plus the
   computed total-elapsed line, and `node_timings["report"]` is available only in
   `ContractState` (and any later re-render), not in this file. Likewise the footer's
   `error_count` reflects only **upstream** errors: the body is serialized *before*
   the write attempt, so a write failure (which sets `error_count: 1` in state,
   AC-19) can't appear in a file that failed to write — the write-failure signal
   lives in `ContractState.error_count`, not in the report file. Both are inherent to
   a node rendering itself and are **not** defects.

JSON output needs **no** renderer module: it is `report.model_dump_json(indent=2)`
directly in the node (see below). Both formats derive from the one `ContractReport`
(D1), so a finding count in the Markdown header always equals the JSON's
`len(findings)` (AC-17a).

---

### Report Node

#### [NEW] `backend/app/graph/nodes/report_agent.py`

The module that touches `ContractState` for Node 7. It orchestrates: timestamp →
assemble → render → **write JSON then Markdown** → return partial dict. All I/O and
all failure handling live here; the renderers stay pure.

```python
import app.config as _config  # module import so tests can monkeypatch (Node 2/4/5/6 precedent)

logger = logging.getLogger("contractsentinel.report")

# Re-exposed module-level names for monkeypatching (mirrors risk_score_agent.py:42-49):
REPORT_OUTPUT_DIR = _config.REPORT_OUTPUT_DIR
REPORT_MD_FILENAME_TEMPLATE = _config.REPORT_MD_FILENAME_TEMPLATE
REPORT_JSON_FILENAME_TEMPLATE = _config.REPORT_JSON_FILENAME_TEMPLATE
REPORT_EVIDENCE_TEXT_MAX_CHARS = _config.REPORT_EVIDENCE_TEXT_MAX_CHARS
```

**Internal flow:**
```
1.  start_time = time.monotonic(); current_node = "report"
    document_id = state.get("document_id", "unknown")
    generated_at = datetime.now(timezone.utc).isoformat()   # D8 — one timestamp per run
2.  report_model = assemble_report(state, generated_at, REPORT_EVIDENCE_TEXT_MAX_CHARS)
    evidence_trail = build_evidence_trail(report_model, generated_at)
    #   (both pure; on ingest_error, assemble_report returns the minimal report — Edge Case 1)
3.  md_text   = render_markdown(report_model)
    json_text = report_model.model_dump_json(indent=2)
4.  Resolve paths from config templates + REPORT_OUTPUT_DIR (Path, backend/-relative).
    mkdir(parents=True, exist_ok=True) on the output dir.
5.  WRITE ORDER — JSON first, then Markdown (spec AC-19a):
      a. write json_path  (json_text)
      b. write md_path    (md_text)
    report_path = str(md_path)      # points at the human deliverable (D1)
    Wrap 4+5 in one try/except (see failure path).
6.  elapsed = time.monotonic() - start_time
7.  Aggregate metrics log (spec §9) via logger.info("ReportAgent completed", extra={
        total_clauses, validated_findings, clean_clauses, high, medium, low,
        evidence_rows=len(evidence_trail), report_chars=len(md_text),
        write_ok=True, elapsed_seconds=round(elapsed,4)})
8.  return {"report_path": report_path,
            "evidence_trail": evidence_trail,
            "current_node": current_node,
            "node_timings": {current_node: elapsed}}
    # NOTE: no processing_completed_at (D2); no clauses key; no key owned by Nodes 1–6.
```

**Failure path (spec §2.2 / §7.6 / AC-19 / AC-19a, Edge Case 3):**
```
except (OSError, ValidationError) as exc:
    logger.error("ReportAgent: failed to write report for document_id=%s: %s",
                 document_id, exc)
    # Partial-pair cleanup (AC-19a): if json_path was written but md_path failed,
    # unlink the orphan JSON so state never implies a pair that isn't consistent.
    _cleanup_orphan(json_path, md_path)
    elapsed = time.monotonic() - start_time
    return {"report_path": None,                 # Optional[str] — unset on failure
            "evidence_trail": evidence_trail,    # DELIBERATE — see note below
            "current_node": current_node,
            "node_timings": {current_node: elapsed},
            "error_count": 1}                    # single health signal (spec §7.6)
```

**Deliberate decision — `evidence_trail` is emitted even on write failure (review
item 2).** The trail is computed *before* the file write, from in-memory state, so
it is fully valid regardless of whether the disk write succeeds; the trail is the
evidence *audit* and does not depend on the report file existing. Emitting it on the
failure path keeps the audit intact for a downstream consumer even when the rendered
report couldn't be persisted, and it is consistent with AC-15's key list (which
never gates `evidence_trail` on `report_path`). This is an intentional choice, not an
oversight — it is locked by `test_write_failure_still_emits_trail` (§2 node tests) so
it is never later "corrected" as a bug.

**Key invariants (make these explicit so they are testable):**
- **`report_path` is a real, existing, non-empty file on success; `None` on write
  failure** (AC-10/11/19). It is a path string, never the report body (constitution
  §6, AC-11).
- **JSON is written before Markdown** so `report_path` (the Markdown) is only ever
  set once its JSON sibling exists; a mid-pair failure leaves no orphan the state
  points at (AC-19a).
- **`clauses` is never in the return** and is byte-for-byte unchanged (AC-16).
- **`processing_completed_at` is never in the return** (D2 / AC-15).
- **`error_count` appears iff — and exactly once when — the write failed** (AC-19).
- **No LLM call, ever** (D3): the node imports no `ollama` / model constant.

**Helper — `_cleanup_orphan(json_path, md_path)`:** if `json_path` exists but
`md_path` does not (JSON write succeeded, Markdown failed), unlink `json_path` and
log a debug line; best-effort, swallows its own `OSError` so cleanup never masks the
original error.

---

### Graph Wiring

#### [MODIFY] `backend/app/graph/builder.py`

Register the `report` node and **replace** the two temporary `→ END` placeholders
(`builder.py:121-122`) with the fan-in into `report`, then add `report → END`
(spec §7.1, AC-22/23):

```python
from app.graph.nodes.report_agent import report_agent

# Inside build_graph(), replacing the two `graph.add_edge("redline"/"skip_redline", END)` lines:

# ── Node 7: ReportAgent (terminal assembly node) ──────────────────────────────
# Constitution §2 item 7. Both Node-6 branches converge here via plain LINEAR
# add_edge (fan-in) — NOT a conditional edge — so the graph still has exactly the
# two permitted domain conditional edges (CRAG internal, route_on_risk). ReportAgent
# reads the fully-populated ContractState, writes the report file(s), and returns
# report_path + evidence_trail (spec §7.1). The node name "report" matches the
# pinned current_node value (spec §7.5) so state-key identity never drifts from the
# graph node name (constitution §8).
graph.add_node("report", report_agent)
graph.add_edge("redline", "report")        # was END (feature-008 placeholder)
graph.add_edge("skip_redline", "report")   # was END (feature-008 placeholder)
graph.add_edge("report", END)
```

Update the module docstring's "Current scope" note (`builder.py:4-11`) to include
Node 7 and remove the two "→ END temporarily / → report once feature-009 exists"
placeholders. The node-name string `"report"` matches the pinned `current_node`
value (spec §7.5) so state-key identity never drifts from the graph node name
(constitution §8).

**Note on conditional-edge count:** after this change the graph's conditional
sources are unchanged — the ingest error-guard (non-domain) and `route_on_risk`
(Node 6, domain); CRAG stays internal per-clause. `report` is reached only by the
two linear fan-in edges and exits by one linear edge, so spec AC-24 (zero new
`add_conditional_edges`) holds.

---

### Unit Tests

#### [NEW] `backend/tests/unit/test_report_models.py`

Pydantic model tests (`app/models/report.py`) — pure, no I/O:

| Test | Verifies |
|------|----------|
| `test_contract_report_roundtrips_json` | A built `ContractReport` serializes with `model_dump_json` and re-parses equal |
| `test_finding_rewrite_state_values` | `rewrite_state` accepts the three labels; `suggested_rewrite` present only for `"rewritten"` |
| `test_summary_counts_are_ints` | `ReportSummary` fields typed `int`; H/M/L + clean are non-negative |
| `test_optional_fields_default_none` | `section_number`/`risk_level`/`path_taken`/etc. default to `None`; `evidence`/`findings` default to `[]` |
| `test_malformed_finding_raises` | Missing required `clause_text` / wrong type → `ValidationError` (caught by the node → AC-19 path) |

#### [NEW] `backend/tests/unit/test_report_assembler.py`

Tests for `assemble_report` + `build_evidence_trail` — pure functions over fixture
`ContractState` dicts:

| Test | Verifies |
|------|----------|
| `test_only_validated_become_findings` | Mixed VALIDATED/DISCARDED/None → findings are exactly the VALIDATED set (AC-1) |
| `test_findings_ordered_by_position` | Findings sorted by `position` regardless of dict order (AC-2) |
| `test_summary_counts_correct` | `total`/`validated`/`clean`/H/M/L match the fixture; clean = total − validated (D4/AC-9) |
| `test_rewrite_state_three_way` | absent key → `"not_eligible"`; `None` → `"unavailable"`; str → `"rewritten"` (AC-8) |
| `test_evidence_text_truncated` | A snippet longer than the cap is truncated in the model (AC-12a, Edge Case 6) |
| `test_missing_snippet_fields_placeholder` | Snippet missing `snippet_text`/`source_reference` → placeholder, no `KeyError` (Edge Case 7) |
| `test_empty_evidence_finding` | Validated finding with `[]`/`None` evidence → `evidence == []`, no crash (AC-7) |
| `test_missing_risk_level_placeholder_path` | Validated finding with `risk_level is None` still assembles (rendered as placeholder — Edge Case 4) |
| `test_ingest_error_minimal_report` | `ingest_error` set → `findings == []`, `ingest_error` populated, zeroed summary (Edge Case 1/AC-20) |
| `test_enum_or_str_risk_level` | `risk_level` as `RiskLevel` enum **or** its str both normalize to the same `.value` (checkpoint round-trip robustness) |
| `test_assembler_does_not_mutate_state` | Input `state`/`clauses` unchanged after the call (AC-16 precondition) |
| `test_trail_validated_only` | `build_evidence_trail` emits rows only for validated findings with ≥1 snippet; discarded contribute none (D5/AC-13) |
| `test_trail_row_shape_and_mapping` | Every row has exactly `{clause_id, evidence_source, evidence_text, retrieved_at}`; mapping per AC-12a |
| `test_trail_shared_timestamp` | All rows in one call share one `retrieved_at == generated_at` (D8/AC-12a) |
| `test_trail_empty_when_no_evidence` | Validated findings all without evidence → `[]` |

#### [NEW] `backend/tests/unit/test_report_renderer.py`

Tests for `render_markdown` — pure, string assertions over built `ContractReport`s:

| Test | Verifies |
|------|----------|
| `test_header_counts_rendered` | Headline shows validated count + H/M/L + clean count (AC-9/D4) |
| `test_findings_in_position_order` | Finding sections appear in ascending `position` (AC-2) |
| `test_finding_shows_severity_and_rationale` | Each finding renders `risk_level` + `risk_rationale` (AC-3) |
| `test_finding_shows_text_and_locator` | `clause_text` + `section_number` (or `"§ n/a"` placeholder) shown (AC-4) |
| `test_provenance_rendered` | `path_taken` + `confidence_score` shown; graceful when `None` (AC-5) |
| `test_evidence_block_rendered` | Each snippet's text + source shown; block omitted when no evidence (AC-6/7) |
| `test_rewrite_three_states_distinct` | `"rewritten"` shows the rewrite; `"unavailable"` shows the marker; `"not_eligible"` shows neither — all three distinguishable (AC-8) |
| `test_severity_unavailable_placeholder` | `risk_level is None` finding renders "severity unavailable", no crash (Edge Case 4) |
| `test_clean_clauses_counted_not_listed` | Clean count present; no clean-clause text enumerated (D4) |
| `test_ocr_caveat_when_ocr_used` | `ocr_used` → caveat line in header (Edge Case 8) |
| `test_zero_findings_clean_report` | Zero validated → well-formed "no findings" body, non-empty string (AC-18) |
| `test_ingest_error_minimal_body` | `ingest_error` → "could not be processed" header echoing the message (AC-20) |
| `test_footer_renders_partial_timings` | Missing/partial `node_timings`/`error_count` render without crash (Edge Case 10) |
| `test_footer_renders_total_elapsed` | Footer shows a total-elapsed line computed from `generated_at − processing_started_at` (spec §2.3 item 4, review item 1); `"unknown"` when `processing_started_at` absent |

#### [NEW] `backend/tests/unit/test_report_agent.py`

Tests for the node — real (pure) renderers, real temp-dir I/O via `tmp_path`;
`REPORT_OUTPUT_DIR` monkeypatched to `tmp_path`. No mocks needed except the
write-failure injection.

| Test | Verifies |
|------|----------|
| `test_writes_md_and_json_pair` | Both files exist at the configured stem; JSON deserializes; its finding count == Markdown headline count (AC-17a/D1) |
| `test_report_path_points_at_existing_nonempty_md` | `report_path` → existing, non-empty `.md` file (AC-10) |
| `test_report_body_not_in_state` | Return carries a path string, not the report body (AC-11, constitution §6) |
| `test_evidence_trail_in_return` | `evidence_trail` present, rows validated-only, correct shape (AC-12/12a/13) |
| `test_current_node_pinned` | `current_node == "report"` and same key in `node_timings` (AC-14) |
| `test_partial_update_only` | Return keys exactly `{report_path, evidence_trail, current_node, node_timings}` on success; **no** `processing_completed_at`, `clauses`, or `error_count` (AC-15) |
| `test_clauses_not_mutated` | Input `clauses` byte-for-byte unchanged (AC-16) |
| `test_paths_from_config` | Output dir + both filename templates read from monkeypatched config, not hardcoded (AC-17) |
| `test_zero_findings_writes_clean_report` | Zero validated → files written, `report_path` set, no `error_count` (AC-18) |
| `test_ingest_error_minimal_report` | `ingest_error` set → minimal report written, `report_path` set, no LLM, no crash (AC-20) |
| `test_empty_clauses_writes_and_warns` | `clauses == {}` (no ingest_error) → valid "no findings" report + warning (AC-21) |
| `test_write_failure_emits_error_count` | Injected `OSError` on write → `report_path is None`, `error_count == 1`, no crash (AC-19, Edge Case 3) |
| `test_write_failure_still_emits_trail` | On an injected write failure the return still contains the computed `evidence_trail` (deliberate — review item 2) |
| `test_partial_pair_failure_cleans_orphan_json` | JSON write succeeds, Markdown write raises → orphan JSON removed, `report_path is None`, `error_count == 1` (AC-19a) |
| `test_json_written_before_markdown` | Assert write order (e.g. via a sequencing spy) so `report_path` never precedes its JSON sibling (AC-19a) |
| `test_no_llm_imported` | The node module references no `ollama` / model constant (D3) |

#### [MODIFY] `backend/tests/unit/test_config.py`

| Test | Verifies |
|------|----------|
| `test_report_constants_match_spec` | `REPORT_OUTPUT_DIR`, `REPORT_MD_FILENAME_TEMPLATE`, `REPORT_JSON_FILENAME_TEMPLATE`, `REPORT_EVIDENCE_TEXT_MAX_CHARS` match spec §6 |
| `test_report_constants_correct_types` | `str` for the dir + templates; `int` for the char cap |
| `test_report_filename_templates_have_document_id` | Both templates contain the `{document_id}` field and differ only by extension (D6) |
| `test_report_no_llm_constant` | No `REPORT_*_TIMEOUT` / model / circuit-breaker constant exists (D3) |

---

### Integration Tests

#### [NEW] `backend/tests/integration/test_report_graph.py`

Node 7 wired into the graph. `REPORT_OUTPUT_DIR` monkeypatched to `tmp_path`;
upstream Self-RAG / RiskScore / Redline LLM boundaries mocked (or a pre-built
`clauses` fixture injected) — no live Ollama.

| Test | Verifies |
|------|----------|
| `test_graph_reaches_report_and_ends` | A doc with a mix of validated/discarded clauses + ≥1 rewrite reaches `report`, produces a `report_path` that exists, terminates at END (AC-25) |
| `test_graph_redline_branch_fans_into_report` | The `redline` branch flows into `report` (not END) and a report is written (AC-22) |
| `test_graph_skip_redline_branch_fans_into_report` | The `skip_redline` branch flows into `report` and a report is written (AC-22) |
| `test_graph_report_to_end` | `report` has a single outgoing edge to END (AC-23) |
| `test_graph_ingest_error_still_reaches_report` | An ingest error short-circuits Nodes 2–6 but the terminal report path is exercised as specced (or documented if the ingest guard still routes to END — see note) |
| `test_graph_no_new_conditional_edges` | Inspect `build_graph().get_graph()`: `report` is reached only by linear edges from `redline`/`skip_redline`; conditional sources are exactly the ingest guard + `route_on_risk`; CRAG stays internal (AC-24) |
| `test_graph_evidence_trail_populated` | After a full run, final state's `evidence_trail` has validated-only rows with the D8 shared timestamp (AC-12a/13) |
| `test_graph_checkpointing_after_report` | State checkpointed after Node 7. Test builds its **own** graph with `SqliteSaver.from_conn_string(":memory:")` (wrapped `try/except ImportError → pytest.skip`) since `build_graph()` compiles with no checkpointer; asserts terminal state retrievable. Mirrors `test_redline_graph.py` |

> **Note on the ingest-error graph path:** the existing ingest guard
> (`route_after_ingest`, `builder.py:46`) short-circuits an ingest error straight to
> `END`, so in the *current* graph an ingest-errored run never reaches `report`. The
> spec's Edge Case 1 / AC-20 (`report` writes a minimal report on `ingest_error`) is
> therefore exercised at the **node** level (`test_report_agent.py::test_ingest_error_minimal_report`),
> and is defensive belt-and-suspenders at the graph level. The integration test
> asserts the *current* wiring (error → END) and documents that the node-level
> minimal-report behavior is what protects a future graph where the guard is removed
> or `report` is reachable on error. Flagged so the implementer doesn't "fix" the
> guard to force `report` on error — that would be a `builder.py` scope change beyond
> this feature.

---

## 3. Dependency & Import Map

```
app/config.py
    └── app.graph.state (RiskLevel)   # ALREADY imported — Report adds no new import

app/models/report.py
    └── pydantic (BaseModel, Field)    # boundary model per constitution §4
        # NO app.graph.state import — models are plain-typed (str/int/Optional);
        # enum values are pre-normalized to .value by the assembler before construction

app/graph/nodes/renderers/__init__.py
    └── re-exports assemble_report, build_evidence_trail, render_markdown

app/graph/nodes/renderers/report_assembler.py
    ├── typing (stdlib)
    ├── app.graph.state (ValidationStatus, ClauseType, RiskLevel, RetrievalPath)  # read/normalize
    └── app.models.report (ContractReport, ReportFinding, ReportSummary, ReportEvidence)
        # PURE — no I/O, no ollama, no app.config (limits passed in as args)

app/graph/nodes/renderers/markdown_renderer.py
    └── app.models.report (ContractReport)      # PURE — string in/out, no I/O

app/graph/nodes/report_agent.py
    ├── time, logging, datetime, pathlib (stdlib)
    ├── pydantic (ValidationError — for the write/assembly try/except)
    ├── app.graph.state (ContractState)
    ├── app.graph.nodes.renderers (assemble_report, build_evidence_trail, render_markdown)
    └── app.config — imported AS A MODULE (`import app.config as _config`) with the
                     Report constants re-exposed as module-level names, read by bare
                     name so tests can monkeypatch them (Node 2/4/5/6 precedent).

app/graph/builder.py
    ├── (existing imports unchanged)
    └── app.graph.nodes.report_agent (report_agent)   # NEW
```

**No** `ollama` / `httpx` / `concurrent.futures` (no LLM — D3), **no**
`numpy` / `faiss` / `duckduckgo_search` (no vectors/retrieval). The only new runtime
dependency touched is `pydantic`, already in the stack (`002-tech-stack.md` §4).

---

## 4. Implementation Order

Following TDD per constitution §7 — tests written and confirmed failing before
implementation.

| Step | Action | Files |
|------|--------|-------|
| 1 | Write config tests for the new Report constants (confirm failing) | `tests/unit/test_config.py` |
| 2 | Add the `# ── Report thresholds` block to config (no new import) | `app/config.py` |
| 3 | Run config tests (confirm passing) | — |
| 4 | Write model tests (confirm failing) | `tests/unit/test_report_models.py` |
| 5 | Implement the Pydantic report models | `app/models/report.py` |
| 6 | Run model tests (confirm passing) | — |
| 7 | Create the `renderers/` package marker | `app/graph/nodes/renderers/__init__.py` |
| 8 | Write assembler + trail tests (confirm failing) | `tests/unit/test_report_assembler.py` |
| 9 | Implement `report_assembler.py` (`assemble_report` + `build_evidence_trail`) | `app/graph/nodes/renderers/report_assembler.py` |
| 10 | Run assembler tests (confirm passing) | — |
| 11 | Write Markdown renderer tests (confirm failing) | `tests/unit/test_report_renderer.py` |
| 12 | Implement `markdown_renderer.py` | `app/graph/nodes/renderers/markdown_renderer.py` |
| 13 | Run renderer tests (confirm passing) | — |
| 14 | Write node tests (confirm failing) | `tests/unit/test_report_agent.py` |
| 15 | Implement `report_agent.py` (assemble → render → write JSON-then-MD → return) | `app/graph/nodes/report_agent.py` |
| 16 | Run node tests (confirm passing) | — |
| 17 | Update graph builder (add `report` node, rewire fan-in, `report → END`) | `app/graph/builder.py` |
| 18 | Write and run integration tests (mocked upstream) | `tests/integration/test_report_graph.py` |
| 19 | Full test suite pass (all existing + new) | all tests |

---

## 5. Design Decisions & Rationale

### Fan-in via linear edges, not a conditional edge (spec §7.1)
Both Node-6 branches converge on `report` with two plain `add_edge`s. A fan-in is
not a routing decision — nothing chooses *between* successors — so it needs no
`add_conditional_edges` and does not touch constitution §2's "exactly 2 conditional
edges" count (AC-24). This is the cheapest wiring that reunites the branches, and it
mirrors how every prior placeholder `→ END` was re-pointed at its real successor.

### Pydantic model as the single serialization source (constitution §4, D1)
The report is modeled once as `ContractReport`; JSON is `model_dump_json()` and
Markdown walks the same object. This makes the two output formats structurally
incapable of drifting (AC-17a) and puts the "validated-only, ordered, three-state
rewrite" policy in **one** place (the assembler) rather than duplicated across two
renderers. The model lives in `app/models/` — the §4 boundary-model home — never in
graph state.

### Pure assembler + pure renderers, all I/O in the node
`assemble_report`, `build_evidence_trail`, and `render_markdown` are pure functions:
deterministic, no I/O, no state mutation, trivially testable without mocks. Every
file write and every failure branch lives in `report_agent.py`. This is the
deterministic analogue of the Node 3–6 split (pure `scorers`/`drafters`/`retrievers`
helper + stateful node), and it is why Node 7 needs no LLM mock anywhere in its unit
suite.

### `evidence_trail` built from the assembled model, not raw state (D5, AC-13)
Deriving the trail from `report.findings` (already validated-only and ordered)
guarantees the trail's scope equals the rendered findings' scope — they cannot
disagree about which clauses are shown. One walk, one D5 policy point.

### `retrieved_at` = report-generation time (D8)
CRAG persists no per-snippet retrieval timestamp (`make_snippet()` produces exactly
`{snippet_text, source_reference}`), so the honest, self-contained value is
report-generation time, stamped once and shared by all rows. This narrows `001` §3's
field gloss to "when the trail row was compiled" — a documentation-only refinement,
no schema change (constitution §10). A true per-snippet timestamp would be a §10
change to `001`/CRAG, deferred as a future refinement if ever needed.

### JSON-before-Markdown write order (D1, AC-19a)
`report_path` points at the Markdown. Writing JSON first means `report_path` is only
set after its JSON sibling already exists, so a mid-pair failure never leaves state
pointing at a Markdown file whose sibling is missing. On a Markdown failure after a
JSON success, the orphan JSON is unlinked so disk never holds a half-pair the state
implies. This is the report's analogue of the single-health-signal discipline
(`error_count: 1`, spec §7.6).

### No LLM, no circuit breaker, no retry (D3)
"Compiles" (constitution §2) is deterministic assembly. Adding an LLM summary would
pull in the timeout/circuit-breaker machinery of Nodes 4–6 for no Phase-1 benefit; it
is explicitly deferred (D3). A file-write failure is a genuine but rare health event,
surfaced once via `error_count: 1` rather than retried — a retry loop against a
full/read-only disk would just burn the same failure.

### `processing_completed_at` left to the runner (D2)
`processing_started_at` is already pipeline-level and node-agnostic
(`test_ingest_agent.py::test_ingest_does_not_set_processing_started_at`); the
symmetric completion timestamp belongs to the same runner layer. Node 7 stays a
pure assembly node and does not reach outside its own concern. (See §6 for the
integration caveat that no runner currently stamps it.)

### Logging strategy (spec §9)
Named logger `contractsentinel.report`. `ContractState` carries only aggregate
`node_timings["report"]`; all run-level roll-ups (findings roll-up, redline
coverage, report size/truncation, write outcome + latency) are emitted as
`logger.info(..., extra={...})` structured records for the eval harness
(`002-tech-stack.md` §3i) — never added as state fields. Mirrors
`risk_score_agent.py` / `redline_agent.py`.

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Output directory unwritable (permission / disk full / bad path) | Report not persisted | `try/except (OSError, ValidationError)` → `report_path=None`, `error_count:1`, no crash (AC-19); `mkdir(parents=True, exist_ok=True)` first |
| JSON writes but Markdown fails, leaving a half-pair on disk | State points at a missing/incomplete deliverable | JSON-first write order + orphan-JSON cleanup; `report_path` set only after both succeed (AC-19a) |
| `suggested_rewrite` three states collapsed (absent vs None) | "not eligible" misrendered as "rewrite failed" | Assembler flattens to an explicit `rewrite_state` via a `_MISSING` sentinel, in one place (AC-8); `test_rewrite_state_three_way` locks it |
| `risk_level`/`clause_type` deserialized as str after checkpoint round-trip | Enum-only handling breaks | Normalize via str-Enum `.value` (works for enum or str); `test_enum_or_str_risk_level` locks it |
| Unbounded evidence text bloats checkpointed `evidence_trail` | State-size growth (constitution §6) | Assembler truncates `snippet_text` to `REPORT_EVIDENCE_TEXT_MAX_CHARS` before model construction (Edge Case 6) |
| A malformed clause record raises mid-serialization | Pipeline crash at the terminal node | Pydantic validates at assembly inside the node `try`; a bad record surfaces as the AC-19 failure path, not an uncaught exception |
| `processing_completed_at` written by nobody | Terminal timestamp silently missing | **Out of scope for Node 7 (D2).** Flagged here as an integration assumption: the future graph-runner / API feature must stamp both `processing_started_at` and `processing_completed_at`; recorded so it is not lost (spec §8a D2 caveat) |
| Discarded clause content leaks into the report | Violates constitution §2.4 | Findings + trail are validated-only in one policy point (assembler); clean clauses are counted, not enumerated (D4); `test_only_validated_become_findings` + `test_trail_validated_only` lock it |
| A future `add_conditional_edges` sneaks in on the fan-in | Architecture drift (constitution §2) | `test_graph_no_new_conditional_edges` asserts `report` is reached only by linear edges and the conditional set is unchanged (AC-24) |
| Report body accidentally embedded in state | Violates constitution §6 | Node returns only `report_path` (a string); `test_report_body_not_in_state` locks it |

---

## 7. Out of Scope for This Plan

- **MCP delivery of the report (Drive / Gmail)** — a separate future feature
  (`specs/010-*`) that reads `report_path` and writes `mcp_delivery_status`; not one
  of the fixed 7 nodes (spec §5.1 / D7).
- **`processing_completed_at` / any runner-layer or API-invocation timestamping** —
  D2; owned by the future runner/API feature (§6 caveat).
- **LLM-generated executive summary** — deferred (spec §5 / D3); no LLM in Phase 1.
- **Enumerating clean/discarded clauses** — counted only (D4); `DISCARDED` content is
  never shown (constitution §2.4).
- **HTML / PDF output** — would add a tech-stack dependency (`002` change); deferred
  (D1). Markdown + JSON only.
- **DB persistence, retention/cleanup of report files** — Phase-2 (constitution §2
  PHASE-2-DEFERRED); Node 7 writes a file to a configured directory and returns its
  path (spec §5.6).
- **Re-scoring / re-validating / re-retrieving** — Nodes 5 / 4 / 3 own those; Node 7
  consumes their outputs as given (spec §5.2).
- **Drafting or editing rewrites** — RedlineAgent (Node 6); Node 7 renders
  `suggested_rewrite` as-is (spec §5.3).
- **Human-in-the-loop review / accept-reject UI** — PERMANENTLY CUT (spec §5.4).
- **Progress streaming / SSE** — API-layer concern, not this node (spec §5.7).
- **Removing the ingest error-guard so `report` is reached on `ingest_error`** — a
  `builder.py` scope change beyond this feature; the node's minimal-report behavior
  is defensive (integration-test note in §2).

---

## 8. Reference: Constitution & Spec Traceability

- **Constitution §2** — Node 7 is item 7 (ReportAgent); the fan-in adds no
  conditional edge (spec §7.1, this plan §2 builder / §5). §2.4 (discarded never
  shown) → validated-only findings + counted-not-listed clean clauses (D4/D5).
- **Constitution §3** — all thresholds/paths in `app/config.py`; this plan §2 (config
  block), AC-17.
- **Constitution §4** — Pydantic at the file boundary; `app/models/report.py`, never
  in graph state (this plan §2, §5).
- **Constitution §5** — partial-update rule; node returns only
  `report_path`/`evidence_trail`/`current_node`/`node_timings` (+ `error_count:1` on
  write failure). This plan §2 (node flow).
- **Constitution §6** — state minimality; report body on disk, only `report_path`
  (+ bounded `evidence_trail`) in state. This plan §2, §5, §6.
- **Constitution §7** — TDD order; this plan §4.
- **Constitution §8** — pinned `current_node == "report"` == graph node name; this
  plan §2 (node, builder).
- **Constitution §9** — local-model latency: N/A (no LLM call — D3); the node is
  deterministic and the fastest in the pipeline.
- **Constitution §10** — no `001` schema change; `retrieved_at` value semantics are a
  doc-only narrowing (D8), and `report_path`/`evidence_trail`/`processing_completed_at`
  are pre-reserved fields (spec §2, §8a D8).
- **Constitution §11** — branch `feature/009-report-agent` (top of this file).
- **Spec §8a D1–D8** — resolved decisions carried into this plan §1.
