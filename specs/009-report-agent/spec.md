# ReportAgent Specification

> Feature 009 — **Node 7** of the fixed 7-node pipeline (constitution §2:
> "7. ReportAgent — compiles final report + evidence trail"). This is the
> **terminal** node of the Phase-1 graph. It is a pure **assembly** node: it
> reads the fully-populated `ContractState` produced by Nodes 1–6, serializes a
> human-readable report to a file, and writes the file reference plus a
> structured `evidence_trail` back into state. It makes **no** routing decision
> and **no** LLM call (resolved D3 — the Phase-1 core is fully deterministic).
>
> **Design decisions resolved with the reviewer on 2026-07-06** (were Open
> Questions Q1–Q7 in a prior draft; now pinned in §8a): **D1** report format =
> Markdown body + sibling JSON; **D2** the graph runner (not ReportAgent) stamps
> `processing_completed_at`; **D3** no LLM executive summary in Phase 1; **D4**
> clean clauses are counted, not enumerated; **D5** `evidence_trail` covers
> validated findings only; **D6** deterministic filename `{document_id}` under
> `data/reports/`; **D7** MCP Drive/Gmail delivery is a separate future feature
> (`specs/010-*`), out of scope here; **D8** `evidence_trail.retrieved_at` =
> report-generation timestamp (CRAG persists no per-snippet retrieval time). This
> spec has **no remaining open questions** and is ready for plan.md.

## 1. Problem Statement

By the time control reaches Node 7 every per-clause field the pipeline will ever
produce already exists in `ContractState`:

- IngestAgent (Node 1) wrote document metadata + `extracted_text`.
- ClauseSplitter (Node 2) wrote each clause's `text` / `position` / `section_number` / `clause_type`.
- CRAG (Node 3) wrote `confidence_score` / `path_taken` / `evidence_snippets`.
- Self-RAG (Node 4) wrote the verdict fields + `final_status` (`VALIDATED` / `DISCARDED`).
- RiskScore (Node 5) wrote `risk_level` / `risk_rationale` for validated findings.
- Redline / SkipRedline (Node 6) wrote `suggested_rewrite` for redline-eligible findings.

Nothing downstream will add clause data. **ReportAgent's job is to turn that
accumulated state into the deliverable a human actually reads:** an ordered,
readable report of the *validated* findings — each with its severity, rationale,
supporting evidence, and (where available) a suggested safer rewrite — plus a
machine-consumable `evidence_trail` that records which source supported which
finding. It is the pipeline's single point of **presentation assembly**.

**Where it sits in the fixed architecture.** Both Node-6 branches (`redline` and
`skip_redline`) currently terminate at `END` as a placeholder (feature-008 spec
§7.5, `builder.py:121-122`, each carrying the comment
`# → "report" once feature-009 (Node 7) exists`). This feature adds the `report`
node and **rewires both of those edges** to point at it, exactly as every prior
node's `→ END` placeholder was rewired when its successor arrived. `report` then
has a single outgoing edge to `END`. Because both Node-6 branches converge here,
`report` is a **fan-in** node reached by two plain linear `add_edge`s — it
introduces **no** new conditional edge, preserving the constitution's "exactly 2
conditional edges" invariant (§2).

**Assembly, not generation.** "Compiles" in constitution §2 is deliberate:
Node 7 *aggregates and formats* data other nodes already produced and validated.
It does not re-judge, re-score, re-rank, or re-retrieve anything. This keeps the
node deterministic and cheap — the natural terminal contrast to the generative
Nodes 3–6. Resolved D3: **no** LLM-written executive summary in Phase 1, so the
core report is fully deterministic and the node makes zero LLM calls.

**Constitution §2.4 — discarded findings are never shown.** Self-RAG's
`DISCARDED` outcome is defined as "never shown to user". ReportAgent is the node
that enforces that boundary: the reader-facing findings list contains **only**
`final_status == VALIDATED` clauses. Discarded clauses are excluded from the
findings body, from the `evidence_trail` (D5), and appear only within the
aggregate clean-clause count (D4) — never enumerated.

**State Minimality (constitution §6).** The rendered report can be large
(every finding, its evidence, its rewrite). Per §6, large content is stored as a
**file reference**, not embedded in graph state. ReportAgent therefore writes the
report body to a file and puts only the **path** (`report_path`) into state. The
structured `evidence_trail` — bounded, per-finding audit rows — *is* stored in
state because `001` reserves it there with an `operator.add` reducer.

**Boundary crossing → Pydantic (constitution §4).** Writing the report to disk is
a system-boundary crossing (file I/O). Per §4 the report's structure is modeled
with a **Pydantic** model and validated before serialization, while the internal
graph state stays TypedDict. The two are never mixed: the Pydantic report model is
built *from* `ContractState`, not stored *in* it.

## 2. Inputs and Outputs

All fields reference `ContractState` as defined in
`specs/001-contract-state-schema.md`. **This spec introduces no new
`ContractState` field names.** Every key it writes — `report_path`,
`evidence_trail`, `processing_completed_at` — is already reserved in `001` §3
(under the `# Added by ReportAgent` and pipeline-metadata comment blocks). Any
Pydantic report model this feature defines is a *serialization* type that lives
outside graph state (constitution §4), not a state field.

### 2.1 Reads from `ContractState`

- `clauses`: `Dict[str, Dict[str, Any]]` — the primary input. For each clause
  record ReportAgent reads (all already populated upstream):
  - `final_status`: `Optional[ValidationStatus]` — **the gate**: only
    `VALIDATED` records appear as findings (constitution §2.4). `DISCARDED` /
    `None` are excluded from the findings body.
  - `text`: `str` — the original clause language.
  - `position`: `int` — 1-indexed document order; the sort key for findings.
  - `section_number`: `Optional[str]` — e.g. `"1.2"`, `"Article 5"`; shown for locatability.
  - `clause_type`: `Optional[ClauseType]` — shown as the finding's category.
  - `risk_level`: `Optional[RiskLevel]` — severity (present on validated findings).
  - `risk_rationale`: `Optional[str]` — *why* it's risky (present on validated findings).
  - `suggested_rewrite`: `Optional[str]` — three-state per feature-008 §2.2:
    **absent** (never attempted / clean), **`None`** (attempted, no rewrite),
    **non-empty str** (successful rewrite). The report renders these three states
    distinctly (AC-8).
  - `evidence_snippets`: `Optional[List[Dict[str, Any]]]` — each snippet is
    `{snippet_text: str, source_reference: str}` (per `001` §3); the raw material
    for the per-finding evidence display **and** for `evidence_trail` rows.
  - `confidence_score`: `Optional[float]`, `path_taken`: `Optional[RetrievalPath]`
    — shown as provenance ("local KB" vs "web fallback", with score).
- `document_id`: `str` — report identity; part of the output filename (D6).
- `original_filename`: `str` — shown in the report header.
- `uploaded_at`: `str` (ISO) — shown in the report header.
- `ocr_used`: `bool`, `ocr_confidence`: `Optional[float]` — surfaced as a
  data-quality caveat in the header when `ocr_used` is true (a low-confidence OCR
  extraction is context the reader should have).
- `processing_started_at`: `str` (ISO) — shown; also the start point if this node
  computes total elapsed time (D2: the runner, not this node, stamps completion).
- `node_timings`: `Dict[str, float]`, `error_count`: `int` — surfaced in a
  small "processing summary" footer (per-node timing + whether any node reported a
  health event). Read-only; ReportAgent does not modify prior timings, it only
  adds its own `report` entry.
- `ingest_error`: `Optional[Dict[str, str]]` — checked defensively; if set, the
  pipeline never produced findings, so ReportAgent emits a minimal "could not
  process" report rather than an empty findings list (Edge Case 1).

### 2.2 Writes to `ContractState`

Per the partial-update rule (constitution §5) ReportAgent returns **only** the
keys it updates:

| Field | Type | Reducer (per `001`) | Description |
|-------|------|---------------------|-------------|
| `report_path` | `Optional[str]` | last-write | Filesystem path (backend/-relative, mirroring `CRAG_KB_INDEX_PATH`) to the serialized **Markdown** report just written (D1). The JSON sibling is written alongside at the same stem (`.json`); `report_path` points at the Markdown file as the canonical human deliverable. The report **body** lives in these files, not in state (constitution §6). Typed `Optional[str]` to match `001` §3 and to allow the unset/`None` state on a write failure (AC-19, Edge Case 3). |
| `evidence_trail` | `List[Dict[str, Any]]` | `operator.add` | Append-only audit rows. No prior node writes this key, so ReportAgent's list *is* the whole trail. Each row: `{clause_id: str, evidence_source: str, evidence_text: str, retrieved_at: str}` (shape fixed by `001` §3). One row per (validated finding, supporting-evidence-snippet) — validated-only (D5). **Row-field mapping (D8):** `clause_id` = the clause's key in `clauses`; `evidence_source` = the snippet's `source_reference`; `evidence_text` = the snippet's `snippet_text`, truncated to `REPORT_EVIDENCE_TEXT_MAX_CHARS`; `retrieved_at` = the single report-generation ISO timestamp (per D8 — CRAG persists no per-snippet retrieval time). |
| `current_node` | `str` | last-write | Pinned to the literal `"report"` — matches the graph node name registered in `builder.py` (constitution §8; mirrors how Nodes 2–6 pin their names). |
| `node_timings` | `Dict[str, float]` | `merge_dicts` | `{"report": <elapsed_seconds>}`. |

**`processing_completed_at` is NOT written by ReportAgent (D2).** By symmetry with
`processing_started_at` — which is explicitly pipeline-level and set by the graph
runner, never by a node (`test_ingest_agent.py::test_ingest_does_not_set_processing_started_at`)
— the terminal completion timestamp is the **graph runner's** responsibility. This
keeps node vs. runner responsibilities clean. ReportAgent reads
`processing_started_at` for the report header but stamps no completion time.

It writes **no** clause fields (it does not modify the `clauses` dict at all),
**no** `mcp_delivery_status` (that is a future delivery step — §5.4), and **no**
key owned by Nodes 1–6.

**Error accounting.** A failure to *write the report file* (e.g. disk/permission
error) is a genuine pipeline-health event and increments `error_count` by 1 (via
`operator.add`), mirroring how Nodes 4–6 emit a single health signal — see
Edge Case 3. Routine content variation (few findings, no rewrites) is **not** an
error and never touches `error_count`.

### 2.3 Report file contents (the serialized artifact, not state)

The file `report_path` points to contains, at minimum:

1. **Header** — `original_filename`, `document_id`, `uploaded_at`,
   `processing_started_at`, OCR caveat when `ocr_used`, and a headline count
   ("N validated findings: H high / M medium / L low").
2. **Findings** — one section per `VALIDATED` clause, ordered by `position`,
   each showing: `section_number` + `clause_type`, `risk_level`,
   `risk_rationale`, the original `text`, its `suggested_rewrite` rendered per its
   three states (AC-8), provenance (`path_taken` + `confidence_score`), and its
   supporting `evidence_snippets`.
3. **Clean-clause summary** — an aggregate count of non-validated clauses only,
   never an enumeration (D4).
4. **Processing footer** — per-node `node_timings`, `error_count`, and total
   elapsed time.

The **file format** is a Markdown body plus a sibling JSON (D1); `report_path`
points at the Markdown file.

## 3. Acceptance Criteria

Each criterion is written to become a test case directly. File I/O is exercised
against a temp directory (`tmp_path`); no LLM is involved at all (the node is
fully deterministic — D3). Throughout, "finding" means a clause record with
`final_status == VALIDATED`.

### Report assembly

1. **Only validated clauses become findings**: Given a `clauses` dict mixing
   `VALIDATED`, `DISCARDED`, and `final_status is None` records, the rendered
   report's findings section contains exactly the `VALIDATED` records and none of
   the others (constitution §2.4). Assert both inclusion and exclusion.

2. **Findings are ordered by `position`**: Findings appear in ascending
   `position` order regardless of `clauses` dict insertion order.

3. **Each finding renders its severity and rationale**: For every validated
   finding the report contains its `risk_level` and its `risk_rationale` text.

4. **Each finding renders original clause text and locator**: Every finding shows
   its `text` and its `section_number` (or a defined placeholder when
   `section_number is None`).

5. **Provenance is shown**: Each finding shows its `path_taken`
   (local-KB vs web-fallback) and `confidence_score` when present, and degrades
   gracefully when either is `None`.

6. **Evidence snippets are rendered per finding**: For a finding with N
   `evidence_snippets`, the report shows each snippet's `snippet_text` and
   `source_reference`.

7. **Empty-evidence finding still renders**: A validated finding whose
   `evidence_snippets` is `[]`/`None` renders its severity/rationale/text without
   an evidence block and without crashing.

8. **`suggested_rewrite` three states render distinctly**: A finding with a
   non-empty `suggested_rewrite` shows the rewrite; a finding with
   `suggested_rewrite is None` (attempted, unavailable) shows a defined
   "no rewrite available" marker; a finding where the key is **absent**
   (not redline-eligible) shows neither — and the three are visually
   distinguishable (feature-008 §2.2).

9. **Header counts are correct**: The headline count equals the number of
   validated findings, broken down by `risk_level` (H/M/L), and matches the number
   of finding sections actually rendered.

### State outputs

10. **`report_path` points at a file that exists and is non-empty**: After the
    node runs, `report_path` is set to a path that exists on disk and whose
    contents are non-empty.

11. **Report body is NOT embedded in state**: The returned state update contains a
    `report_path` string but does **not** contain the full report text as a state
    value (constitution §6). Assert the update carries a path, not the body.

12. **`evidence_trail` is built with the fixed row shape**: Every appended row has
    exactly the keys `clause_id`, `evidence_source`, `evidence_text`,
    `retrieved_at` (`001` §3), and no others.

12a. **Row-field mapping is correct (D8)**: For a row derived from clause `C`'s
    snippet `S`, `clause_id == C`, `evidence_source == S["source_reference"]`,
    `evidence_text == S["snippet_text"]` (truncated to
    `REPORT_EVIDENCE_TEXT_MAX_CHARS`), and `retrieved_at` is a valid ISO timestamp.
    All rows produced by a single run share **one** `retrieved_at` value
    (report-generation time — CRAG persists no per-snippet retrieval time, D8).

13. **`evidence_trail` covers the intended scope**: The set of `clause_id`s in the
    trail matches the D5 scope: validated findings that have ≥1 evidence snippet.
    A validated finding with no evidence contributes no trail row; a discarded
    clause contributes none.

14. **`current_node` pinned**: After the node runs, `current_node == "report"` and
    the same string is the key in the returned `node_timings` dict.

15. **Partial update only**: The returned dict contains only
    `report_path`, `evidence_trail`, `current_node`, `node_timings` (plus
    `error_count: 1` iff the file write failed — AC-19). It contains **no**
    `processing_completed_at` (runner-owned, D2), **no** `clauses` key, and no
    key owned by Nodes 1–6.

16. **Clauses are not mutated**: The `clauses` dict is byte-for-byte unchanged
    after the node runs (no field added to or removed from any clause record).

17. **Output path/filenames read from config**: The output directory and both
    filename templates (`.md` and `.json`) are read from `app.config` constants
    (constitution §3), never hardcoded inline.

17a. **Markdown + JSON pair written (D1)**: After the node runs, both a Markdown
    file (at `report_path`) and a JSON sibling at the same stem exist; the JSON
    deserializes to a structure whose finding count matches the Markdown's headline
    count (AC-9).

### Degenerate & failure paths

18. **Zero validated findings → valid clean report**: For a `clauses` dict with
    zero `VALIDATED` records (all discarded / none), the node still writes a
    well-formed report stating "no findings", sets `report_path`, makes no error,
    and does not crash. This is the normal SkipRedline-path outcome, not an error.

19. **Report-file write failure**: If writing the report file raises (permission /
    disk error), the node logs an error, returns `error_count: 1` (health signal),
    and does not crash the graph. `report_path` behavior on failure is defined
    (either unset/`None` or pointing at a partial-write cleanup) — pinned in
    plan.md; the `Optional[str]` typing (§2.2) permits the unset state.

19a. **Partial Markdown/JSON pair failure (D1)**: The two files are written in a
    **pinned order — JSON first, then Markdown** — so that `report_path` (which
    points at the Markdown) is set to a path **only** once its JSON sibling already
    exists; if the JSON write fails, no Markdown is written and `report_path` stays
    unset (AC-19 path). If the Markdown write fails after a successful JSON write,
    the node treats it as a report-file write failure (AC-19: `error_count: 1`,
    `report_path` unset) and the orphan JSON is cleaned up. The node never leaves
    state pointing at a Markdown file whose JSON sibling is missing. (Exact cleanup
    mechanics — unlink vs. leave-and-log — are finalized in plan.md.)

20. **`ingest_error` set → minimal report**: If `ingest_error` is non-`None`, the
    node writes a minimal "document could not be processed" report (echoing the
    ingest error message), sets `report_path`, and makes no LLM call. It does not
    attempt to enumerate findings from an empty `clauses` dict (Edge Case 1).

21. **Empty `clauses` dict (no ingest_error)**: For `clauses == {}` with no
    `ingest_error`, the node writes a valid "no findings" report and logs a
    warning (defensive; should not normally occur if ingest succeeded).

### Graph wiring

22. **`report` node registered and fan-in wired**: `builder.py` registers the
    `report` node and adds plain linear edges `redline → report` **and**
    `skip_redline → report`, replacing the two temporary `→ END` placeholders
    (feature-008 §7.5).

23. **`report → END`**: `report` has a single outgoing edge to `END`.

24. **No new conditional edge introduced**: An inspection asserts this feature adds
    **zero** `add_conditional_edges` calls — the graph still has exactly the two
    permitted domain conditional edges (CRAG internal, `route_on_risk`) plus the
    ingest error-guard. `report` is reached only by linear edges.

25. **Whole-graph smoke**: A compiled-graph run over a fixture `ContractState`
    (with a mix of validated/discarded clauses and at least one rewrite) reaches
    `report`, produces a `report_path` that exists, and terminates at `END`.

## 4. Edge Cases

1. **`ingest_error` set upstream**: `clauses` is empty and no findings exist.
   Emit a minimal report echoing the ingest error (AC-20). Same defensive
   `ingest_error` check every prior node performs, but the *outcome* differs: this
   is the terminal node, so it still produces a deliverable rather than a silent
   pass-through.

2. **Zero validated findings** (all `DISCARDED` / `None`): a well-formed
   "no findings identified" report (AC-18). This is the expected output for a
   contract Self-RAG found nothing worth flagging in — a success, not an error.
   It is also the normal state on the SkipRedline branch (feature-008 Edge Case 3).

3. **Report-file write fails** (permission denied, disk full, bad path): log an
   error, emit `error_count: 1` (AC-19), do not crash. A terminal node that can't
   persist its artifact is a real health event, distinct from a clean run —
   mirrors the single-health-signal pattern of Nodes 4–6. Whether to retry the
   write once or fail fast is pinned in plan.md.

4. **A validated finding missing `risk_level` / `risk_rationale`** (defensive —
   RiskScore's fail-safe guarantees a level, but a malformed re-run could omit
   one): render the finding with a defined placeholder (e.g. "severity
   unavailable") rather than crashing on a `None`. The finding is still shown —
   never silently dropped.

5. **`suggested_rewrite` absent vs `None` vs string**: rendered as three distinct
   states (AC-8) — never collapse "not eligible" (absent) with "attempted but
   failed" (`None`). Reading it alongside `risk_level` per feature-008 §2.2.

6. **Very large report** (hundreds of findings, long rewrites): the report body
   goes to a file, not state (constitution §6), so state size is bounded to the
   path string + the per-finding `evidence_trail` rows. If `evidence_trail` itself
   grows large, its per-row `evidence_text` is truncated to a config cap
   (`REPORT_EVIDENCE_TEXT_MAX_CHARS`) — pinned in §6.

7. **Evidence snippet missing `snippet_text` or `source_reference`** (defensive):
   substitute a defined placeholder for the missing field in both the rendered
   evidence block and the trail row; never `KeyError`.

8. **OCR-extracted document** (`ocr_used == True`, low `ocr_confidence`): surface a
   data-quality caveat in the report header so the reader knows the source text may
   contain extraction errors. Not an error; informational.

9. **Duplicate / re-run**: ReportAgent re-run on the same `document_id` overwrites
   the prior report file at the deterministic path (D6) and re-emits
   `evidence_trail`. Because `evidence_trail` uses `operator.add`, a re-run within
   the *same* graph invocation would double rows — but a re-run is a fresh
   invocation with a fresh state, so this is not a concern in normal operation
   (noted for the plan's idempotency section).

10. **`node_timings` / `error_count` absent or partial** (defensive): the
    processing footer renders whatever is present and omits missing rows without
    crashing.

## 5. Out of Scope

ReportAgent (Node 7) does **not** handle:

1. **Delivering the report via MCP (Google Drive / Gmail)** — writing
   `mcp_delivery_status` is a **separate future step**, not part of the fixed
   7-node graph. `001` §3 labels that key "Added by MCP delivery step", and the
   constitution's PERMANENTLY-CUT list permits Drive+Gmail MCP *only*. Node 7
   produces the artifact and its `report_path`; a later feature (prospective
   `specs/010-*`) reads that path and delivers it. Feature-008 §5.9 already points
   here. **This boundary is load-bearing** and resolved (D7): delivery is feature
   010, not 009.

2. **Assigning or re-deriving severity, validation, or evidence** — those are
   Nodes 5 / 4 / 3 respectively. ReportAgent consumes `risk_level`,
   `final_status`, and `evidence_snippets` as given and never re-computes them.

3. **Drafting or editing suggested rewrites** — that is RedlineAgent (Node 6,
   `specs/008-*`). ReportAgent renders `suggested_rewrite` as-is and never
   generates or modifies clause language. (No executive summary is generated in
   Phase 1 — D3.)

4. **Human-in-the-loop review / accept-reject of findings or rewrites** — no
   review UI (consistent with the PERMANENTLY-CUT "no audit-log UI / dashboard"
   items). The report is a read-only deliverable.

5. **Legal correctness guarantees** — the report presents LLM-derived findings and
   suggestions for human review; it makes no claim of legal soundness (inherited
   from feature-008 §5.7 and the Self-RAG/RiskScore framing).

6. **Persisting the report to the database / long-term storage / retention** —
   Phase-1 writes a file to a configured directory; DB persistence and retention
   policy are Phase-2 concerns (constitution §2 PHASE-2-DEFERRED "Retention
   policy"). ReportAgent only writes the file and returns its path.

7. **Streaming progress / SSE** — the tech stack lists `sse-starlette` for the API
   layer, but progress streaming is an API-layer concern, not this node's.

## 6. Configurable Constants

Per constitution §3, all thresholds/paths live in `backend/app/config.py`. This
spec adds a new `# ── Report thresholds` section. Values below are **final**
(the format/filename decisions D1/D6 are resolved).

```python
# ── Report thresholds ──────────────────────────────────────────────────────────
# Source: specs/009-report-agent/spec.md §6

REPORT_OUTPUT_DIR: str = "data/reports"
# Directory (backend/-relative, mirroring CRAG_KB_INDEX_PATH's anchoring) where
# ReportAgent writes serialized report files. Created if absent. (D6)

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

There is intentionally **no** LLM/timeout/circuit-breaker constant, because the
node makes no LLM call (D3; contrast Nodes 3–6). Both report files share one
deterministic stem so the Markdown/JSON pair always stays in sync on a re-run.

## 7. Pinned Design (safe for plan.md)

These follow directly from the constitution / shared conventions and are safe to
plan against regardless of how the Open Questions resolve:

### 7.1 Terminal fan-in node, no new conditional edge
`report` is registered as a node; `redline → report` and `skip_redline → report`
replace the two feature-008 `→ END` placeholders; `report → END` is the single
exit. Two plain linear `add_edge`s in, one out — **zero** new conditional edges,
preserving constitution §2's "exactly 2 conditional edges" (AC-22/23/24).

### 7.2 Assembly node, deterministic core
The core report is a pure function of `ContractState` — no re-scoring, no
retrieval, no routing. This makes Node 7 the cheap, deterministic terminal
contrast to the generative Nodes 3–6, and makes its tests fully deterministic
without mocking an LLM. Resolved D3: **no** LLM executive summary in Phase 1, so
the node makes zero LLM calls of any kind.

### 7.3 File reference in state, body on disk (constitution §6)
The report body is written to `REPORT_OUTPUT_DIR/<filename>` and only
`report_path` enters state. `evidence_trail` rows (bounded, truncated per
`REPORT_EVIDENCE_TEXT_MAX_CHARS`) are the only report-derived content that lives in
state, because `001` reserves that key there.

### 7.4 Pydantic at the file boundary (constitution §4)
The report structure is modeled with a Pydantic model, built from the TypedDict
`ContractState` and validated before serialization. The Pydantic model is a
serialization type only — it is never stored in graph state, keeping the
TypedDict/Pydantic separation §4 mandates.

### 7.5 Pinned state-key value `"report"`
`current_node` and the `node_timings` key are the literal `"report"`, matching the
graph node name in `builder.py` (constitution §8; mirrors Nodes 2–6).

### 7.6 Single health signal on write failure
A report-file write failure emits `error_count: 1` exactly once (AC-19), mirroring
the single-health-signal discipline of Nodes 4–6. Routine content variation is not
an error.

## 8. Design Decisions and Open Questions

### 8a. Resolved / pinned (safe for plan.md)

Structural invariants (follow directly from the constitution / shared conventions):
- Terminal fan-in wiring, no new conditional edge (§7.1).
- Findings body = `VALIDATED` clauses only, ordered by `position` (§2.4, AC-1/2).
- File reference in state; body on disk; Pydantic at the boundary (§7.3/§7.4).
- Pinned `current_node == "report"` (§7.5).
- Single `error_count` health signal on write failure only (§7.6).
- All paths/thresholds in `app.config` (§6, constitution §3).
- No new `ContractState` field names (§2).

Design decisions resolved with the reviewer on 2026-07-06 (were open Q1–Q7 in a
prior draft; now pinned):

- **D1 — Report format = Markdown body + sibling JSON** (was Q1). `specs/002-tech-stack.md`
  ships **no** HTML/PDF renderer (PyMuPDF is parse-only), so both formats are chosen
  because they are dependency-free: Markdown is the human-readable deliverable that
  `report_path` points at; the JSON sibling (same stem) is the machine-readable form
  for later consumers (e.g. the API layer, or feature-010 delivery). HTML/PDF are
  deferred — adding them later is a §002 tech-stack change, not a Node-7 change.
  Confirms §6 (`REPORT_MD_FILENAME_TEMPLATE` / `REPORT_JSON_FILENAME_TEMPLATE`),
  AC-17a.

- **D2 — The graph runner stamps `processing_completed_at`; ReportAgent does not**
  (was Q2). Symmetric with `processing_started_at`, which is pipeline-level and set
  by the runner, never a node
  (`test_ingest_agent.py::test_ingest_does_not_set_processing_started_at`). Keeps
  node vs. runner responsibilities clean; ReportAgent's partial update therefore
  never contains `processing_completed_at` (AC-15). Confirms §2.2.
  **Integration caveat (for plan.md assumptions):** the cited test only proves
  *ingest* does not set it — it does **not** prove any runner currently does. At the
  time of writing no graph-runner / API-invocation layer exists yet, so
  `processing_completed_at` (and `processing_started_at`) are presently written by
  **nobody**. That is an out-of-scope Phase-1 integration gap owned by the future
  runner/API feature, not by Node 7; plan.md must record it as an explicit
  assumption so it is not silently lost.

- **D3 — No LLM executive summary in Phase 1** (was Q3). The node stays fully
  deterministic and cheap — zero LLM calls, no timeout/circuit-breaker constant
  (contrast Nodes 3–6). An optional summary can be layered on later once real
  reports exist, without changing the core. Confirms §7.2 / §6.

- **D4 — Clean (non-validated) clauses are counted, not enumerated** (was Q4). The
  header shows an aggregate (e.g. "42 clauses reviewed · 3 findings · 39 clean").
  Listing clean clauses is noise and risks re-surfacing `DISCARDED` content that
  §2.4 says is never shown. Confirms §2.3 / AC-9.

- **D5 — `evidence_trail` covers validated findings only** (was Q5). One row per
  (validated finding, supporting snippet). Consistent with §2.4 (the trail is the
  evidence *behind the shown findings*, not an audit of discarded material). Confirms
  §2.2 / AC-13.

- **D6 — Deterministic filenames `{document_id}.md` / `.json` under `data/reports/`**
  (was Q6). A re-run overwrites in place (Edge Case 9); history/retention is a
  Phase-2 concern (constitution §2 PHASE-2-DEFERRED). Confirms §6.

- **D7 — MCP Drive/Gmail delivery is a separate future feature (`specs/010-*`), out
  of scope for 009** (was Q7). Delivery is not one of the fixed 7 nodes; Node 7 ends
  at "report written to disk + `report_path`/`evidence_trail` in state". Confirms
  §5.1 and feature-008 §5.9.

- **D8 — `evidence_trail.retrieved_at` = report-generation timestamp; per-snippet
  retrieval time is not persisted upstream** (new, raised in review 2026-07-06). CRAG
  (Node 3) builds every evidence snippet via `make_snippet()`
  (`retrievers/__init__.py:34`), which produces **exactly**
  `{snippet_text, source_reference}` — **no** timestamp is stored on the snippet or
  anywhere in `ContractState`. ReportAgent therefore cannot recover the true
  retrieval instant. Resolved to **Option (a)**: ReportAgent stamps `retrieved_at`
  with **one report-generation ISO timestamp** (`datetime.now(timezone.utc)`, taken
  once at node start so all rows in a run share it), and this spec **explicitly
  narrows** `001` §3's "when evidence was retrieved/validated" gloss to "when the
  trail row was compiled" for Phase 1. This is a documentation-only narrowing of
  `001` (field type/reducer unchanged — a light constitution §10 touch, flagged),
  not a schema change. Rejected: **(b)** adding a per-snippet timestamp back in
  `001`/CRAG (a real constitution §10 schema change, out of Node 7's scope, deferred
  as a possible future refinement if true retrieval time is ever needed); **(c)**
  leaving `retrieved_at` empty (breaks the fixed row shape AC-12 asserts). The
  row-field mapping this fixes is pinned in §2.2 below.

### 8b. Open Questions

No remaining open questions. This spec is considered final and ready for plan.md
(constitution §1 / §8).

## 9. Evaluation

Node 7 does no confidence scoring or retry validation itself, so it has no
precision/recall-style metrics of its own. But as the pipeline's terminal
aggregation point it is the natural place to log **run-level roll-ups** (following
the `logger.info(..., extra={...})` structured-log pattern of the prior nodes;
these live in log records, **not** in `ContractState`):

1. **Findings roll-up** — per run: total clauses, validated-finding count, and the
   H/M/L severity split. The headline "what did this contract look like" signal.

2. **Redline coverage** — of validated findings, how many carried a non-empty
   `suggested_rewrite` vs. `None` vs. absent — the terminal counterpart to
   feature-008 §9 metric 2, computed over the same data the report renders.

3. **Report size & truncation** — rendered report length and how often
   `evidence_trail` `evidence_text` hit `REPORT_EVIDENCE_TEXT_MAX_CHARS`, to
   calibrate that cap.

4. **Write outcome & latency** — whether the file write succeeded (and
   `error_count` emissions from Edge Case 3), plus node wall-clock time (the value
   that also feeds `node_timings["report"]`). Expected to be the fastest node in
   the pipeline given the deterministic core (§7.2).

These support tuning `REPORT_EVIDENCE_TEXT_MAX_CHARS` and validating that the
report faithfully reflects upstream state once real sample contracts are processed.
