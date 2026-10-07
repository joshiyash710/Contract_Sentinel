# Feature 061 — Spec: Per-user learned clause KB (grow the local KB from analyzed contracts)

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/061-learned-clause-kb` (constitution §11).

> When a user analyzes a contract, the **validated-finding** clauses from that run are embedded and appended
> to a **per-user, private** FAISS clause index; CRAG retrieval (node 3) then searches **both** the shared
> base KB and that user's private index, so the local KB grows every run, judgment quality improves, and
> fewer clauses fall through to web search. Governed by the **2026-10-07 / feature-061 constitution
> amendment** (§2). **No new graph node/edge; no `ContractState` change; no migration.**

## 1. Problem statement

The local clause KB (§2 node 3) is a single curated FAISS index (`data/kb/clauses.faiss` +
`clauses_meta.jsonl`), loaded **read-only** and cached once per process (`kb_retriever.load_kb`), and searched
by `crag_retrieval_agent` for every clause: `search_kb` returns a top-1 cosine `top_score`; `top_score >=
CRAG_CONFIDENCE_THRESHOLD` (0.73) routes to `LOCAL_KB`, else to `WEB_FALLBACK`. The KB never changes, so the
system never learns from the contracts it sees, and any clause the curated corpus doesn't cover keeps going
to web search run after run.

The owner wants the KB to **learn**, while preserving per-user isolation (§019) and *improving* — not
degrading — judgment quality. This feature:
1. **Appends** each run's **validated-finding** clauses (Self-RAG-passed only — high signal, not raw
   boilerplate) to an index **private to the uploading account**, as a **runner post-run side-effect**.
2. **Augments** CRAG: node 3 also searches the requesting user's private index and takes the **better**
   match (max `top_score`, merged snippets) across it and the base KB — so a clause the base KB would have
   sent to web can now clear 0.73 locally once the user has seen a similar clause before.

### Position relative to the constitution
- **Authorized by the feature-061 amendment (§2, 2026-10-07).** Read it: the per-user learned KB is in scope;
  it adds **no node and no edge** (write = runner side-effect outside the graph; read = in-node augmentation
  of node 3's existing FAISS search), and **no `ContractState` field** (the `user_id` CRAG needs is passed
  via the LangGraph run **`config`/`configurable`** channel, not graph state — so `specs/001` is unchanged).
- **§019 per-user isolation reinforced.** Each account's learned index is private; one account can **never**
  read another's clauses. No sharing, no cross-read, no tenant-admin surface (all still CUT).
- **§3 configurable.** New named config constants (flag + paths + caps); reversible — flag **off** ⇒ today's
  read-only shared KB exactly, no per-user write or read.
- **§8 embedding separation.** Learned clauses are embedded with **BGE-M3** (the embedding model, via the
  existing `embed_query`/embed seam), never the generative model; the per-user index carries the 050
  provider marker so a provider/model mismatch warns, never silently corrupts scores.
- **§2 node 3 / §035.** Only **validated** findings are stored (not arbitrary uploaded text), bounding the
  data-poisoning surface feature 035 hardens. Encryption-at-rest of the stored learned-clause text is a
  noted Tier-3 follow-up (per 036), not this feature.

## 2. Inputs and outputs

### New config (§3) — `app/config.py`
- `CRAG_USER_KB_ENABLED: bool = _env_bool("CRAG_USER_KB_ENABLED", False)` — master flag (default off ⇒
  byte-identical to today). Gates BOTH the post-run write and the CRAG read augmentation.
- `CRAG_USER_KB_DIR: str = "data/kb/users"` — base dir; a user's index lives at
  `{CRAG_USER_KB_DIR}/{user_id}/clauses.faiss` (+ `clauses_meta.jsonl` + `.provider` marker), resolved
  backend-relative exactly like the base KB (`kb_retriever._resolve_backend_path`).
- (Reuse existing `CRAG_TOP_K`, `CRAG_CONFIDENCE_THRESHOLD`, `CRAG_MAX_EVIDENCE_SNIPPETS`,
  `OLLAMA_EMBED_MODEL_NAME` / `EMBED_PROVIDER` / `HF_EMBED_MODEL`.)

### Write side — runner post-run side-effect (`app/runner/core.py` + a new `app/rag`-style helper)
- `run_pipeline(...)` gains a keyword arg **`user_id: Optional[str] = None`** (defaulted ⇒ 011/012/059
  callers byte-identical). Its caller in the runner/registry (which already stamps a job with its creator's
  `user_id`, §019) passes it through.
- After the graph stream completes and `final_state` is available, when `CRAG_USER_KB_ENABLED` **and**
  `user_id` is set: collect the **validated-finding** clauses from `final_state["clauses"]` (the same
  records `report_assembler` turns into `ReportFinding`s — i.e. clauses with a validated finding, not
  discarded ones), embed each clause's text (BGE-M3), and **append** them to the user's index via the new
  helper `user_kb.append_clauses(user_id, items)`:
  - creates the index (+ sidecar + provider marker) on first write for that user;
  - `faiss.add` the L2-normalized vectors; append one metadata row per vector
    (`{"snippet_text": <clause text>, "source_reference": <e.g. "Your contract: <filename> — <RISK> risk">}`,
    matching the base KB row shape `search_kb` reads);
  - holds a **per-user write lock** so concurrent runs for the same user cannot corrupt the index or desync
    `ntotal` vs the sidecar; persists atomically (write to temp + replace);
  - **invalidates the cached user index** so the next search sees the new vectors.
- The write **never raises into the run result** — a KB-write failure is logged and swallowed (the analysis
  + report already succeeded; the learned-KB update is best-effort).

### Read side — CRAG augmentation (`app/graph/nodes/crag_retrieval_agent.py` + `kb_retriever.py`)
- The runner forwards `user_id` into the graph via `config={"configurable": {..., "user_id": user_id}}`
  (alongside the existing `thread_id`). `crag_retrieval_agent` reads it defensively via a guarded
  `langgraph.config.get_config()` call (try/except `RuntimeError` ⇒ `user_id=None`) — **analogous to** feature
  059's guarded `get_stream_writer()` acquisition (not the same API): no runnable context / no config ⇒
  `user_id` is `None` and the node is byte-identical (AC-6).
- `kb_retriever` gains `load_user_kb(user_id) -> Optional[_LoadedKB]` (per-user cache keyed by `user_id`;
  same corruption/row-count guards + provider-mismatch warn as `load_kb`). CRAG loads the base KB (as today)
  and, when `CRAG_USER_KB_ENABLED` and `user_id`, the user KB; it searches **both** and uses the **max**
  `top_score` for the 0.73 routing decision, and merges snippets (base + user), capped at
  `CRAG_MAX_EVIDENCE_SNIPPETS`. With the flag off or no `user_id`, only the base KB is searched (today's path).

### Resolved decisions (inline)
- **D1 — Per-user, private, augmenting (owner).** Isolated index per account; searched **in addition to** the
  base KB (not replacing it); base KB unchanged and still serves accounts with no private index.
- **D2 — Store only validated findings (owner).** High-signal clauses only; discarded/boilerplate clauses are
  never written — this is the quality/poisoning safeguard.
- **D3 — Write is a runner post-run side-effect (§2).** Not a graph node; runs over `final_state`; best-effort
  (never fails the run).
- **D4 — `user_id` via run `config`, not state (§2/§4/§10).** No `ContractState`/`specs/001` change.
- **D5 — Reversible flag `CRAG_USER_KB_ENABLED`, default off.** Off ⇒ today's shared read-only KB exactly.
- **D6 — No dedup in v1.** Near-identical learned clauses may accumulate; dedup/merge is out of scope (§5).

## 3. Acceptance criteria

Backend, offline (pytest; no Ollama — embeddings mocked as the existing CRAG tests do; FAISS runs in-proc on
tiny vectors; a `tmp_path` user-KB dir). The base-KB and embedding seams are already monkeypatch-exercised.

- **AC-1 (flag off ⇒ byte-identical):** with `CRAG_USER_KB_ENABLED=False`, `run_pipeline` writes no per-user
  index and CRAG searches only the base KB — the existing CRAG/runner tests pass unchanged; no user-KB file
  is created.
- **AC-2 (append on completion):** with the flag on + a `user_id` + a `final_state` having M validated
  findings among N clauses, after the run the user's index `ntotal` increased by exactly **M**, the sidecar
  has M new rows, and `len(meta) == index.ntotal` holds.
- **AC-3 (validated-only):** a run whose clauses include discarded/unvalidated records writes **only** the
  validated-finding clauses (M, not N) — asserted on the appended metadata.
- **AC-4 (isolation):** a write for `user_A` creates/updates only `user_A`'s index; a subsequent CRAG run for
  `user_B` loads `user_B`'s index (or none) and **never** returns `user_A`'s clauses as snippets. `load_user_kb`
  is scoped strictly by `user_id` path.
- **AC-5 (augmentation changes routing):** given a query clause whose base-KB `top_score` < 0.73 but whose
  match in the seeded user index ≥ 0.73, CRAG uses the **max** score, routes `LOCAL_KB` (not `WEB_FALLBACK`),
  and includes the user-KB snippet; with the user KB absent it would have gone to web (same input).
- **AC-6 (config-channel read, guarded):** CRAG reads `user_id` from the run `config`; a **direct** node call
  / CLI with no runnable context resolves `user_id=None` and is byte-identical to today (no throw, no user KB)
  — mirrors feature 059's guarded `get_config` acquisition.
- **AC-7 (persist + cache coherence + lock):** after `append_clauses`, the on-disk index reloads with the new
  `ntotal`, the per-user cache is invalidated so the next `load_user_kb`/search sees the new vectors, and two
  concurrent appends for the same user serialize (no lost writes, no `ntotal`/sidecar desync).
- **AC-8 (provider marker):** the user index is written with a `.provider` marker for the active
  `EMBED_PROVIDER`/model; loading a user index whose marker mismatches the active provider logs the 050 warning
  (never fails the load).
- **AC-9 (best-effort write):** if `append_clauses` raises (e.g. embed failure, disk error), `run_pipeline`
  still returns a normal `RunResult` (the error is logged, swallowed) — the learned-KB update never breaks a run.
- **AC-10 (degenerate inputs):** a run with **zero** validated findings writes nothing (no empty index churn);
  flag on but `user_id=None` → no write and no user-KB read, no error.
- **AC-11 (no architecture change):** `git diff main` touches only `app/config.py`, `app/runner/core.py`
  (+ its caller passing `user_id`), `app/graph/nodes/crag_retrieval_agent.py`,
  `app/graph/nodes/retrievers/kb_retriever.py`, the new `user_kb` helper, tests, the 061 specs, and the
  `specs/000` amendment. **No new graph node/edge, no `builder.py` change, no `ContractState`/`specs/001`
  change, no Alembic migration, no new dependency** (faiss/numpy already present). Full backend suite green.

## 4. Edge cases
- **EC-1 — Flag off:** no per-user index exists or is consulted; §2 node-3 behavior is today's (AC-1).
- **EC-2 — No `user_id` (CLI / legacy job / direct graph call):** write skipped, read skipped; byte-identical
  (AC-6/AC-10).
- **EC-3 — Zero validated findings (clean contract):** nothing appended; the user index is untouched (AC-10).
- **EC-4 — First run for a user:** the index + sidecar + provider marker are created on first `append_clauses`.
- **EC-5 — Concurrent runs, same user:** the per-user write lock serializes appends; `ntotal` stays consistent
  with the sidecar (AC-7).
- **EC-6 — Provider/model mismatch:** base KB built under one provider, user index under another → each warns
  via the 050 path; the user index is always written with the active provider so its own scores stay valid.
- **EC-7 — Duplicate / near-identical learned clauses across runs:** allowed to accumulate (D6); may slightly
  inflate the index. Dedup is out of scope. Acceptable.
- **EC-8 — Corrupt / unreadable user index:** `load_user_kb` returns None (same guards as `load_kb`); CRAG
  falls back to the base KB only — no crash.
- **EC-9 — Embedding circuit-breaker open mid-run (existing CRAG behavior):** unchanged; clauses still route
  to web when they can't embed. The user-KB read only augments when a query vector exists.
- **EC-10 — Unbounded growth (keep-forever):** no TTL/GC in v1 (mirrors 056 D1); bounded by disk; reversible
  by disabling the flag / deleting the user dir. Noted, accepted.
- **EC-11 — DOCX contract:** validated findings from a DOCX run are still clause text → they ARE stored and
  retrievable (the learned KB is text-based; unlike 055/057 it is not PDF-only).

## 5. Out of scope
- **Storing all/raw clauses** — only validated findings (D2); boilerplate is never written.
- **A shared / global learned KB across accounts** — PERMANENTLY CUT (§019); learning is strictly per-user.
- **Dedup / merge / decay of learned clauses** (D6/EC-7) — a possible future feature, not v1.
- **Encryption-at-rest of the stored learned-clause text** — Tier-3 deferred (per 036); noted follow-up.
- **Any UI to view, search, curate, or delete the per-user KB** — no KB viewer/dashboard (PERMANENTLY CUT).
- **Rebuilding / re-embedding the base curated KB, or backfilling past runs** into the learned KB — not done;
  only new runs after the flip contribute.
- **Any new graph node/edge, `ContractState` field, or migration** — forbidden by §2 and the amendment.
- **Turso/blob persistence of the per-user index** — v1 stores on disk/`CRAG_USER_KB_DIR` like the base KB;
  a durable-deploy backend for it is a follow-up (noted, not built).

## 6. Evaluation (metrics to log)

This feature changes CRAG confidence routing, so retrieval quality is measured:
- **Per-run (debug log, not state):** scorable-clause count, `LOCAL_KB` count, `WEB_FALLBACK` count, and
  whether each `LOCAL_KB` hit came from the base KB, the user KB, or both (the max source) — so the
  local-hit-rate lift from the learned KB is observable.
- **Offline (optional measurement, like 041/055):** over a repeated-analysis scenario (same/similar
  contracts analyzed across runs with `CRAG_USER_KB_ENABLED` on vs off), record the **web-fallback rate**;
  the expectation the feature must support is that the fallback rate **drops** as the user KB accumulates
  validated clauses (the owner's "avoid web fallback most of the time" goal). No change to the CRAG/Self-RAG
  eval harness is required; this is a one-off offline measurement if run.
- **Guardrail:** validated-only storage (D2) is the quality safeguard — the metric must confirm the learned
  KB does not *increase* spurious `LOCAL_KB` routing on unrelated clauses (seeded-index unit test, AC-5 is the
  positive case; a negative control asserts an unrelated clause still scores < 0.73 against the user KB).

## 7. Open questions

All resolved inline by the owner (2026-10-07); no architecturally-significant item is left to guess:
- **OQ-1 — Isolation + retrieval role → RESOLVED:** per-user private index that **augments** (not replaces)
  the base KB in CRAG (D1); satisfies §019 and raises the local-hit rate.
- **OQ-2 — What to store → RESOLVED: only validated findings** (D2) — the quality/poisoning safeguard.
- **OQ-3 — Where the write happens → RESOLVED: runner post-run side-effect** (D3), `user_id` via run `config`
  (D4) — no node/edge/state change.
- **OQ-4 — Dedup of learned clauses → RESOLVED: out of scope for v1** (D6/EC-7).
- **OQ-5 — Durable (Turso) storage of the per-user index → RESOLVED: out of scope for v1** (disk like the base
  KB; a noted follow-up in §5).

No open questions remain.
