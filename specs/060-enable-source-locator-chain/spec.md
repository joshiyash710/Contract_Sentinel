# Feature 060 — Spec: Enable the source-locator traceability chain by default

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/060-enable-source-locator-chain` (constitution §11).

> The deferred "default-flip" that completes the **055 locator capture → 056 serve-original → 057 viewer**
> clause-traceability chain. 055 (D-decisions), 056 (D2/OQ-1), and 057 (D4/OQ-3) all shipped the two chain
> flags **OFF**, explicitly deferring the default-flip to "a separate change after the 055 extraction-diff
> measurement (055 Task 12)." That measurement has now been run and is clean — this feature flips the two
> defaults to `True`. **Config-default change only.**

## 1. Problem statement

The clause-traceability chain is fully built and merged, but dormant: both backend flags default to `False`,
so in a default deployment IngestAgent uses the plain extraction path (no `page_spans`, no per-finding
`source_locator`) and the uploaded PDF is terminal-deleted on Turso, so `GET /api/jobs/{id}/source` 404s.
The result: the 057 in-workspace viewer and "View in contract" highlights never appear unless an operator
sets two env vars by hand. The two flags, grounded in the current code:

- `PDF_SOURCE_LOCATOR_ENABLED: bool = _env_bool("PDF_SOURCE_LOCATOR_ENABLED", False)` — `app/config.py:297`
  (055). ON ⇒ `pdf_parser` builds `extracted_text` from a `get_text("dict")` pass and stamps each finding's
  `source_locator`; OFF ⇒ the plain `"\n".join(page.get_text())` path, `page_spans=None`, no locators.
- `UPLOAD_SOURCE_RETENTION_ENABLED: bool = _env_bool("UPLOAD_SOURCE_RETENTION_ENABLED", False)` —
  `app/config.py:304` (056). ON ⇒ `registry.mark_terminal` skips the Turso `upload_blobs` delete (keep the
  upload so `/source` works); OFF ⇒ 054 terminal-delete behavior.

The only thing that was gating the flip was the 055 Task 12 extraction-diff concern (OQ-2): does the dict
path's `extracted_text` differ enough from the plain path to change extraction/segmentation? **That
measurement has now been run** (`backend/eval/measure_055_extraction_diff.py`, 30-contract CUAD corpus) and
is clean (see §6). This feature therefore flips **both** defaults to `True`, keeping them env-overridable
(so a deployment can still opt out) and reversible.

### Position relative to the constitution
- **No LangGraph node/edge/`ContractState` change (§2).** The flagged code paths (055 ingest/splitter,
  056 registry/route) already exist and are unchanged; this feature only changes the two default values a
  single `_env_bool(..., False)` resolves to when the env var is unset. No new node, edge, or state field.
- **§3 Configurable Thresholds honored, not violated.** Both flags remain **named config constants**,
  env-overridable; flipping a default value is the intended tuning seam §3 describes ("tuned against real
  sample contracts after implementation") — the §6 measurement is exactly that tuning input.
- **§2 encryption-at-rest amendments (036) honored.** Retained uploads are stored Fernet-encrypted at rest
  (036); keep-forever retention (056 D1) was already the sanctioned posture behind the flag. This feature
  does not store anything new in plaintext and adds no new at-rest surface.
- **Per-user isolation (§019 amendment) unchanged.** `/source` is already `require_auth` + owner-scoped
  (056); flipping retention does not widen access — a retained upload is still private to its owner.
- **No migration, no dependency, no new eval-harness.** `upload_blobs` (054) and `UPLOAD_DIR` (036) already
  exist. The measurement script (055 Task 12) is a one-off offline tool, not part of the runtime or the
  CRAG/Self-RAG eval harness.
- **Reversible (§3).** Setting either env var to `False` restores the prior default exactly.

## 2. Inputs and outputs

### The change
- `app/config.py:297` — `PDF_SOURCE_LOCATOR_ENABLED` default `False` → `True`.
- `app/config.py:304` — `UPLOAD_SOURCE_RETENTION_ENABLED` default `False` → `True`.
- No other production code changes. The flagged branches (055 `pdf_parser`/`ingest_agent`/
  `clause_splitter_agent`, 056 `registry.mark_terminal`/`/source` route) are untouched — only which branch
  runs by default changes.

### Behavioral effect (default deployment, no env override)
- **Ingest/segmentation:** PDFs are parsed via the dict path; `extracted_text` is whitespace-equivalent to
  the plain path (§6: 100% whitespace-collapsed similarity, 0/30 clause-count change), so downstream CRAG /
  Self-RAG / risk / report behavior is unchanged in substance. Each PDF finding gains a `source_locator`.
- **Retention:** a completed job's uploaded PDF is kept (not terminal-deleted) on Turso, encrypted at rest;
  `GET /api/jobs/{id}/source` returns the decrypted PDF to its owner. The 057 viewer + "View in contract"
  highlights now render by default.
- **DOCX / OCR / legacy jobs:** unchanged — DOCX and OCR paths still produce no `source_locator` (055), and
  jobs analyzed before this flip have no locators / may have no retained source (not retroactive).

### Resolved decisions (inline)
- **D1 — Flip BOTH flags together.** The viewer needs both the locators (`PDF_SOURCE_LOCATOR_ENABLED`) and a
  retrievable source (`UPLOAD_SOURCE_RETENTION_ENABLED`) to be useful; 056 D2 / 057 D4 always paired them.
- **D2 — Keep them env-overridable and reversible (§3).** Defaults flip to `True`; a deployment that wants
  the old behavior sets `PDF_SOURCE_LOCATOR_ENABLED=False` / `UPLOAD_SOURCE_RETENTION_ENABLED=False`.
- **D3 — Not retroactive.** Only new runs after the flip capture locators and retain sources; pre-flip jobs
  are unchanged (pre-flip Turso uploads may already be terminal-deleted → `/source` 404, 056 EC-6). Accepted.
- **D4 — Off-path tests become explicit, not weakened.** Existing tests that assert OFF behavior by relying
  on the old default must now set the flag `False` explicitly (via the same monkeypatch seam the ON tests
  use). Making a test hermetic to the default it exercises is not weakening it (§7).

## 3. Acceptance criteria

Backend, offline (pytest; no Ollama). The flag seams are already monkeypatch-exercised by the 055/056 suites.

- **AC-1 (locator default is True):** `app.config.PDF_SOURCE_LOCATOR_ENABLED is True` when the env var is
  unset (a test with `PDF_SOURCE_LOCATOR_ENABLED` absent from the environment).
- **AC-2 (retention default is True):** `app.config.UPLOAD_SOURCE_RETENTION_ENABLED is True` when the env var
  is unset.
- **AC-3 (env override still wins):** with `PDF_SOURCE_LOCATOR_ENABLED=False` (resp.
  `UPLOAD_SOURCE_RETENTION_ENABLED=False`) in the environment, the resolved constant is `False` — the
  `_env_bool` override path is unchanged.
- **AC-4 (full backend suite green):** `python -X utf8 -m pytest -q` passes with the new defaults. Any test
  that previously relied on the default being `False` is updated to set the flag `False` explicitly (D4);
  no test is weakened or deleted to pass (§7), and no ON-path test regresses.
- **AC-5 (055 extraction-diff measurement recorded):** the 055 Task 12 result is recorded in the repo (a
  results note referenced by 055 tasks.md and this spec §6), so the default-flip decision is auditable:
  raw char similarity min ≥ 99.71%, whitespace-collapsed similarity 100%, clause-count change 0/30.
- **AC-6 (no architecture / scope creep):** `git diff main` touches only `app/config.py`, the backend test(s)
  updated for the new defaults, the 055 Task 12 measurement note, and the 060 specs. No node/edge/
  `ContractState`/migration/dependency change; no frontend production-code change (the 057 viewer already
  consumes the data when present).

## 4. Edge cases
- **EC-1 — Env var explicitly set:** an operator with `PDF_SOURCE_LOCATOR_ENABLED=False` (or a `.env` line)
  keeps the old behavior; the flip only changes the *unset* default (AC-3).
- **EC-2 — DOCX / OCR upload:** no `source_locator` (055 is PDF-only); `/source` → 415 for DOCX (056). The
  flip does not change this — DOCX contracts simply have no "View in contract" affordance.
- **EC-3 — Pre-flip (legacy) job:** no locators; on Turso its upload may already be terminal-deleted →
  `/source` 404 and the 057 viewer shows "original no longer available" (056 EC-6 / 057 EC-3). Not retroactive.
- **EC-4 — Local disk deployment:** retention is Turso-relevant; on disk the upload already persisted in
  `UPLOAD_DIR` regardless of the flag (056 EC-2), so flipping retention is a no-op there.
- **EC-5 — A test that asserts OFF behavior without monkeypatching:** would now exercise the ON path and
  could fail; AC-4/D4 require making such a test set the flag `False` explicitly rather than weakening it.
- **EC-6 — Whitespace drift from the dict path (OQ-2 residual):** the dict path drops a few space characters
  at some span boundaries (§6 length deltas of −3…−110 chars, 100% whitespace-collapsed similarity); this is
  the accepted, measured difference and does not change clause counts (0/30) or any AC. Tolerated.

## 5. Out of scope
- **Any change to the flagged code paths themselves** — 055 ingest/splitter and 056 registry/route logic is
  unchanged; this feature only flips which default branch runs. Bugs in those paths are owned by 055/056.
- **A TTL / GC / opt-in retention UI** — keep-forever behind the flag is 056 D1; still not built.
- **Backfilling locators or restoring sources for pre-flip jobs** (D3 / EC-3) — not retroactive.
- **Encryption-at-rest of generated reports / parsed text** — unrelated, still Phase-2-deferred (per 036).
- **Any frontend change** — the 057 viewer, `getSourceUrl`, and the "View in contract" affordance already
  ship and render whenever the data is present; no new UI work.
- **Flipping unrelated flags** (`AUTH_COOKIE_SECURE`, `MCP_DELIVERY_ENABLED`, etc.) — the 057 live-smoke env
  set those for local testing only; they are not part of this chain and keep their own defaults.

## 6. Evaluation (metrics logged — 055 Task 12, the gate for this flip)

The default-flip is gated solely on the 055 extraction-diff concern (OQ-2): whether the flag-ON dict-built
`extracted_text` diverges from the plain path enough to harm extraction/segmentation. Measured offline over
the 30-contract CUAD corpus (`backend/eval/corpus`) by `backend/eval/measure_055_extraction_diff.py`,
comparing the production `_extract_text_with_spans` output vs `"\n".join(page.get_text())` and the regex
clause count on each:

- **Raw char similarity (SequenceMatcher):** mean 99.97%, median 99.98%, **min 99.71%** (n=30).
- **Whitespace-collapsed similarity:** **100.00%** on every document — the only differences are a few spaces
  lost at span boundaries (length deltas −3…−110 chars); no word/content differences.
- **Regex clause-count change:** **0 / 30** documents — segmentation is identical.

Conclusion: the dict path is content-identical to the plain path and does not change clause segmentation, so
flipping `PDF_SOURCE_LOCATOR_ENABLED` on by default is safe. This result is recorded (AC-5) for auditability.
No CRAG/Self-RAG eval-harness change; this is a one-off offline measurement, not a runtime metric.

## 7. Open questions

Resolved inline by the owner (2026-10-07) — they confirm the design in §2 / the decisions / the ACs, no
scope change:
- **OQ-1 — Flip one flag or both? → RESOLVED: both** (D1). The viewer is only useful with locators AND a
  retrievable source; 056/057 always paired them.
- **OQ-2 — Is the dict-path extraction diff acceptable? → RESOLVED: yes** (§6). The 055 Task 12 measurement is
  clean (content-identical, 0 clause-count change), which is precisely what deferred the flip until now.
- **OQ-3 — Retroactive for existing jobs? → RESOLVED: no** (D3 / EC-3). Only new runs capture locators and
  retain sources; pre-flip jobs are unchanged.

No open questions remain.
