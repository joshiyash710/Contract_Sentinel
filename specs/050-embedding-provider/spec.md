# Feature 050 — Embedding provider adapter (HuggingFace bge-m3, Ollama default)

Branch: `feature/050-embedding-provider` (per constitution §11).

## 1. Problem statement

CRAG retrieval (Node 3) embeds each clause with **`bge-m3` via local Ollama** — both the runtime query
embedding (`app/graph/nodes/retrievers/embeddings.py::_call_embed`) and the offline KB index build
(`scripts/build_kb.py::_embed`, which produces `data/kb/clauses.faiss`). This is the single hard blocker
for the **$0 Render deployment** (see [[project_render_turso_deploy]]): Render's free web service has
**512 MB RAM and cannot run Ollama**, so the embedding model must move off-box to a hosted API.

This feature adds an **embedding provider seam** exactly analogous to the generation seam from feature
046 (`app/llm/chat_client.py::get_chat_client`). Generation moved to Groq in 046; **embeddings stayed
local per constitution §8**. This feature adds — for deployment only — the ability to route embeddings
to the **HuggingFace Inference API** (`BAAI/bge-m3`, the same model family) when explicitly configured,
while keeping local Ollama as the **default (byte-for-byte today)**.

### Position relative to the constitution
No graph/edge change, no `ContractState` change, no migration. It swaps *which client* produces the
embedding vector, behind a **named §3 config flag** (`EMBED_PROVIDER`, default `"ollama"`). §7 the
adapter is TDD-unit-tested with the HF client/HTTP **mocked** (no network in the suite). §8 model
separation is **preserved and reinforced**: this is the *embedding* seam and is entirely separate from
the generation seam (046) — the generative Groq/Ollama path is untouched, and the HF path serves
**only** `bge-m3` embeddings, never a generative model. §3 the flag/model/token are named config
constants read at call time.

### The load-bearing invariant (index/query provider parity)
A FAISS vector index is only meaningful if the **query vectors and the indexed vectors come from the
same embedding model+runtime**. Ollama's `bge-m3` (quantized GGUF) and HuggingFace's `bge-m3`
(transformers) can produce **numerically different vectors** for the same text, even at the same nominal
model. Therefore **switching `EMBED_PROVIDER` REQUIRES rebuilding `data/kb/clauses.faiss` through the
same provider**; a HF-query against an Ollama-built index (or vice-versa) yields meaningless cosine
scores. This is stated as a first-class invariant (see §3 D3, §5 EC-7, §7). L2-normalization stays
load-bearing on **both** sides (raw `bge-m3` norm ≈ 25.7; inner-product == cosine only after
normalization) and must be applied identically regardless of provider.

### Privacy / data-egress posture (explicit — mirrors 046)
With `EMBED_PROVIDER=hf`, each runtime query embedding sends **clause text** to **HuggingFace (a third
party)** over TLS — the same category of egress 046 introduced for Groq. Resolution is identical and
**opt-in**:
- **OFF by default** (`EMBED_PROVIDER=ollama`) ⇒ local runs stay fully private; egress happens only when
  an operator deliberately sets `hf` for the deploy.
- **Scope of what is sent:** only the clause/query text already assembled for embedding. **No** auth
  tokens, OAuth credentials, encryption keys, user PII, or file bytes.
- **Secret hygiene:** `HF_API_TOKEN` is read from env/`.env` (gitignored) and **must never be logged**
  (AC-6), mirroring the §032 encryption-key and 046 `GROQ_API_KEY` discipline.
- **Operator duty:** the deploying operator surfaces this in the product privacy/ToS (paired with the
  existing "not legal advice" disclaimer), and documents it in `docs/DEPLOYMENT.md`.
- **Reversibility:** flipping `EMBED_PROVIDER` back to `ollama` restores the fully-local posture. Interim
  opt-in relaxation, not a permanent constitutional change.

## 2. Inputs and outputs

This feature has **no `ContractState` input/output change** (per constitution §4/§1). The embedding
vector is an internal value consumed by CRAG's FAISS search; the downstream state fields it influences
(`clauses[*].confidence_score`, `path_taken`, `evidence_snippets`) are written by the CRAG node
**unchanged**. The "inputs/outputs" below are the module-level contract of the new seam.

### 2.1 New config (§3, env-overridable; near the existing `OLLAMA_EMBED_MODEL_NAME`)
- `EMBED_PROVIDER: str` — `"ollama"` | `"hf"`. **Default `"ollama"`** (byte-for-byte today). Set via env
  so the deploy sets `EMBED_PROVIDER=hf` with no code change.
- `HF_API_TOKEN: str` — from env (`.env` / real env var); default `""`. Never logged. (`load_dotenv()`
  is already called at the top of `config.py` from feature 046 — no change needed there.)
- `HF_EMBED_MODEL: str` — default `"BAAI/bge-m3"` (same model as `OLLAMA_EMBED_MODEL_NAME="bge-m3"`).
- `HF_EMBED_MAX_RETRIES: int` — default `2`. Bounded retry for the HF cold-start `503 "model loading"`
  and transient errors (see EC-2).
- Runtime timeout is **not** new — the runtime path reuses the existing `CRAG_EMBED_TIMEOUT_SECONDS`
  (30 s) that already bounds `_call_embed`. `build_kb.py` remains a synchronous offline script.

### 2.2 The adapter (NEW `app/llm/embed_client.py`)
A factory `get_embed_client(timeout_seconds)` returning a client whose `.embeddings(model, prompt)`
**mimics `ollama.Client.embeddings`'s signature and return shape** so each call site changes by one line:
- `EMBED_PROVIDER == "ollama"` → returns `ollama.Client(timeout=timeout_seconds)` (unchanged path;
  `.embeddings(model=, prompt=)` → `{"embedding": [...]}` or the pydantic `EmbeddingsResponse` that
  `_call_embed` already tolerates).
- `EMBED_PROVIDER == "hf"` → returns an `HFEmbedClient` whose
  `.embeddings(model=None, prompt=<str>) -> {"embedding": <list[float]>}` calls the HF Inference API for
  `HF_EMBED_MODEL` and returns the **raw** (un-normalized) vector as a plain dict under the `"embedding"`
  key — the exact shape `_call_embed` (dict branch) and `build_kb._embed` (`resp["embedding"]`) already
  read. `model` (the Ollama name) is **ignored**; `HF_EMBED_MODEL` wins (mirrors 046 D7/`GROQ_MODEL`).

**Normalization stays in the call sites**, unchanged, so both providers share one normalization code
path (adapter returns raw; caller L2-normalizes). The HF vector MUST be a single pooled
sentence-embedding of dimension **1024** (bge-m3), matching the Ollama vector's dimension so it drops
into the existing FAISS `IndexFlatIP` without shape changes (see EC-4, and Open Question 1 on the exact
HF pooling behavior).

### 2.3 Wire-in (2 embedding call sites — the ONLY functional edits)
- `app/graph/nodes/retrievers/embeddings.py::_call_embed`: replace
  `client = ollama.Client(timeout=timeout_seconds)` with `client = get_embed_client(timeout_seconds)`.
  The `client.embeddings(model=model_name, prompt=text)` call, the dict/pydantic response handling, the
  zero-norm guard, the L2-normalization, and the **`return None` on any failure** (which feeds the CRAG
  embed circuit breaker, `CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD`) are all **unchanged**.
- `scripts/build_kb.py::_embed`: replace the module-level `ollama.embeddings(model=..., prompt=text)`
  with `get_embed_client(<timeout>).embeddings(model=..., prompt=text)` and read `resp["embedding"]` as
  today. The generative-vs-embedding guard in `build_kb` (`OLLAMA_EMBED_MODEL_NAME != OLLAMA_MODEL_NAME`)
  is retained.

The generative seam (`chat_client.py`) and all generative nodes are **NOT** touched.

### 2.4 Output
No new state field, no report/schema change. With `EMBED_PROVIDER=hf` **and a HF-built index**, Node 3's
query embeddings come from HuggingFace; graph, edges, and downstream contracts are unchanged.

## 3. Resolved decisions (inline)
- **D1 — Default `EMBED_PROVIDER=ollama`.** Zero behavior change until explicitly switched; the deploy
  sets `hf` via env. Reversible.
- **D2 — Mimic Ollama's `.embeddings()` dict shape, return RAW vectors.** Smallest blast radius (one line
  per call site); normalization stays in the two call sites so both providers share one normalization
  path and `_call_embed`'s failure/None semantics are preserved verbatim. Note both sites already
  normalize their own result: `_call_embed` L2-normalizes after the response read, and
  `build_kb._embed` L2-normalizes internally after `resp["embedding"]`. The HF adapter returns the raw
  vector so each site's **existing** normalization applies unchanged — no normalization is added,
  moved, or removed by this feature.
- **D3 — Provider parity is an operator invariant, enforced by process, not runtime magic.** The active
  `EMBED_PROVIDER` at index-build time must equal the one at query time. `build_kb.py` writes a small
  **provider+model provenance stamp** alongside the index (e.g. into the existing `clauses_meta` sidecar
  or a `clauses.faiss.provider` marker) so a mismatch is *detectable*; the runtime **logs a loud warning
  (not a hard failure)** if the marker disagrees with the active provider. (Exact marker location is a
  plan detail.)
- **D4 — `HF_EMBED_MODEL="BAAI/bge-m3"` — same model as local.** Keeps the KB semantics and clause
  matching as close as possible to the validated local setup; the vectors still differ enough to force a
  rebuild (D3), but no re-tuning of thresholds is *assumed* (measured in §7).
- **D5 — Bounded retry for HF cold-start.** `HF_EMBED_MAX_RETRIES=2` handles the `503 "model loading"` /
  transient case; on exhaustion the runtime path returns `None` (failsafe, feeds the circuit breaker) —
  never an exception that escapes `_call_embed`.
- **D6 — HF token hygiene mirrors 046.** `HF_API_TOKEN` from env/`.env`, never logged; a missing token
  with `EMBED_PROVIDER=hf` raises a clear config error at client construction (EC-3), not a silent
  degrade.

## 4. Acceptance criteria

### Backend (pytest — all offline, HF client/HTTP MOCKED, no network)
- **AC-1 (factory dispatch):** `get_embed_client(t)` returns an `ollama.Client` when
  `EMBED_PROVIDER="ollama"` and an `HFEmbedClient` when `EMBED_PROVIDER="hf"`.
- **AC-2 (return shape / raw vector):** given a mocked HF response for a 1024-dim `bge-m3` vector,
  `HFEmbedClient.embeddings(model="bge-m3", prompt="x")` returns `{"embedding": [<1024 floats>]}` (raw,
  un-normalized), so `_call_embed`'s existing dict branch + normalization work unchanged.
- **AC-3 (model override, §8):** `HFEmbedClient` calls the (mocked) HF endpoint with `HF_EMBED_MODEL`
  regardless of the `model=` argument passed by the call site, and **only** ever requests an embedding
  model — a test asserts the HF path is never used for a generative model.
- **AC-4 (runtime failure → None, circuit-breaker preserved):** when the mocked HF client raises
  (timeout, HTTP error, or retry-exhausted 503), `embed_query(...)` returns `None` and does **not** raise
  — preserving the input to `CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD`. A zero-norm HF vector also → `None`.
- **AC-5 (reversibility / no-op default — BOTH sites):** with `EMBED_PROVIDER="ollama"` (default), both
  `embeddings.py::_call_embed` and `build_kb.py::_embed` route through `get_embed_client` and construct
  an `ollama.Client` exactly as today (byte-for-byte); a test asserts the embedding path does not touch
  HF when the provider is `ollama`.
- **AC-6 (token hygiene + missing-token error):** the `HFEmbedClient` reads `HF_API_TOKEN` and **never
  logs it** (no log/exception message contains the token — asserted). A missing `HF_API_TOKEN` with
  `EMBED_PROVIDER="hf"` raises a clear config error at construction (not a silent failsafe).
- **AC-7 (config validity):** `EMBED_PROVIDER` ∈ {`ollama`,`hf`}; `HF_EMBED_MODEL` non-empty str;
  `HF_EMBED_MAX_RETRIES` int; `test_config` asserts these and that `EMBED_PROVIDER` default is
  `"ollama"`.
- **AC-8 (dimension parity):** a test asserts the adapter's returned vector length equals the index
  dimension expected by CRAG (1024 for `bge-m3`); a wrong-dimension HF response is rejected → `None`
  (runtime) / raises in `build_kb` (loud offline failure, not a silently corrupt index). Note: 1024 is
  **not** currently a named config constant — the FAISS index derives its dimension from the built
  matrix and the runtime infers it from the loaded index. The plan decides whether to introduce a §3
  named `EMBED_DIM` constant or assert against the loaded index's `d`; the AC's intent (reject a
  wrong-shape vector, never build/query a corrupt index) is provider-agnostic either way.
- **AC-9 (no architecture change):** `git diff` touches only `app/config.py`, `app/llm/embed_client.py`
  (NEW, + `app/llm/__init__.py` if needed), `app/graph/nodes/retrievers/embeddings.py` (one-line swap),
  `scripts/build_kb.py` (one-line swap + provenance stamp), `pyproject.toml` + `uv.lock` (iff a HF client
  dep is added — see Open Question 4), the tests, and `specs/050-**`. **No** graph/edge/`ContractState`/
  migration/generation/frontend change. Whole `pytest` green.

### Live measurement (harness — AC-10; needs a live HF token + rebuilt index)
- **AC-10:** with `EMBED_PROVIDER=hf`, `HF_EMBED_MODEL=BAAI/bge-m3`, **rebuild `clauses.faiss` through
  HF** (`build_kb.py`), then re-run the retrieval eval (`python -m eval.harness.run` + `… score`) on the
  **same gold subset used for the 046 AC-9 measurement** (see `specs/046-groq-llm-provider/RESULTS.md`
  for the exact subset + cached baseline run to diff against). Report retrieval-path hit-rate,
  recall/precision/false-flag vs the Ollama-`bge-m3` baseline,
  and whether the 0.73 CRAG threshold still behaves (see §7). Honest framing: candidate labels
  (`docs/ACCURACY.md`); the Ollama numbers do not automatically carry over.

## 5. Edge cases
- **EC-1 — HF free-tier rate limit (429):** treat like D5 — bounded retry then `None` (runtime) /
  loud failure (offline `build_kb`). A daily/again-later cap that retries cannot clear surfaces as a
  degraded run, not a crash.
- **EC-2 — HF cold-start `503 "model loading"`:** the model may be unloaded on the free tier; use the
  HF client's wait-for-model / bounded retry (D5). If still unavailable after `HF_EMBED_MAX_RETRIES`,
  runtime → `None` (circuit breaker), `build_kb` → abort with a clear message.
- **EC-3 — `HF_API_TOKEN` empty while `EMBED_PROVIDER=hf`:** raise a clear, actionable config error at
  client construction (not a silent degrade).
- **EC-4 — Unexpected HF response shape (per-token matrix instead of a pooled 1024-vector, or nested
  list):** the adapter must normalize the response to a single 1024-float vector; an unparseable/
  wrong-shape response → `None` (runtime) / raises (offline). See Open Question 1 — the exact pooling
  behavior of `bge-m3` on the HF Inference API MUST be pinned before implementation.
- **EC-5 — `EMBED_PROVIDER` unknown value:** config error (AC-7).
- **EC-6 — Empty/whitespace clause text:** unchanged from today — the call sites already pass the text
  through; the provider returns some vector or errors → existing handling applies.
- **EC-7 — Provider/index mismatch (HF query vs Ollama-built index or vice-versa):** cosine scores
  become meaningless. Mitigated by the D3 provenance stamp + loud runtime warning; the true fix is a
  rebuild. **Not** silently corrected. Documented as an operator responsibility in `docs/DEPLOYMENT.md`.

## 6. Out of scope
- Turso/Postgres persistence, blob storage, spin-down resilience, `render.yaml` — features 051–053
  ([[project_render_turso_deploy]]).
- The generation seam (feature 046, `chat_client.py`) — untouched.
- Changing the CRAG algorithm, the 0.73 threshold, the web-fallback path, or FAISS index structure. If
  AC-10 shows the threshold needs re-tuning for HF vectors, that is a **separate, measured** follow-up
  (a §3 constant already), not this feature.
- A second embedding provider beyond ollama/hf; batching multiple clauses per HF call; a self-hosted TEI
  server. Single-text-per-call parity with today is the scope.
- Auto-rebuilding the index when the provider changes — the rebuild is an explicit operator/deploy step
  (D3); this feature only makes a mismatch *detectable*.

## 7. Evaluation (metrics to log — CRAG retrieval feature)
This feature changes the vectors feeding CRAG retrieval, so it carries an evaluation obligation
(constitution retrieval-eval convention). Unit tests (AC-1..AC-9) are the **merge gate**; AC-10 is the
accuracy measurement, run once against a live HF token with a **HF-rebuilt** index:
- **Retrieval-path hit-rate:** fraction of clauses taking `local_kb` (score ≥ 0.73) vs `web_fallback`,
  HF vs Ollama baseline — a large shift signals the 0.73 cutoff needs re-tuning for HF vectors.
- **Confidence-score distribution:** histogram/percentiles of CRAG `confidence_score` under HF vs
  Ollama — detects a systematic scale shift between the two `bge-m3` runtimes.
- **Downstream recall / precision / false-flag** on the gold subset vs the Ollama baseline, framed
  honestly against candidate labels.
- **Dimension/normalization sanity:** confirm 1024-dim, unit-norm vectors on both sides (guards EC-4).

## 8. Notes for plan.md / tasks.md (pointers)
- **Config:** add `EMBED_PROVIDER`/`HF_API_TOKEN`/`HF_EMBED_MODEL`/`HF_EMBED_MAX_RETRIES` near
  `OLLAMA_EMBED_MODEL_NAME`. `load_dotenv()` already present (046) — do not re-add. Read config by bare
  module name for monkeypatch, like `chat_client.py`.
- **Adapter:** `app/llm/embed_client.py` — `get_embed_client(timeout)` + `HFEmbedClient` using raw
  `httpx` (OQ#4 resolved: no new dep) POSTing `{"inputs": prompt}` to
  `https://router.huggingface.co/hf-inference/models/{HF_EMBED_MODEL}/pipeline/feature-extraction` with
  a `Bearer HF_API_TOKEN` header; the 200 body IS the pooled 1024-float list → return
  `{"embedding": that_list}`; ignore the passed `model` in favor of `HF_EMBED_MODEL`; bounded retry (D5)
  on 503/429/timeout; never log the token.
- **Wire-in:** one-line client swap in `embeddings.py::_call_embed` and `build_kb.py::_embed`; add the D3
  provenance stamp in `build_kb`. Generative files untouched.
- **Deps:** **none added** (OQ#4 → raw `httpx`, already a dependency). No `pyproject`/`uv.lock` change;
  the CI dep-audit is unaffected.
- **Tests:** `tests/unit/test_embed_client.py` (AC-1..AC-8, HF mocked); extend the CRAG embedding test
  for the swap (AC-5) + `test_config` (AC-7). **⚠ revert any local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b
  override before committing** (known config-test gotcha). TDD failing-first.
- **Index rebuild (AC-10, operational):** document the `EMBED_PROVIDER=hf … python scripts/build_kb.py`
  rebuild in `docs/DEPLOYMENT.md`; the rebuilt `clauses.faiss` is a deploy artifact, not committed by
  this feature.

## 9. Open questions

**All resolved via a live HF probe (2026-08-29) + decisions below.** Probe: `httpx.post` to
`https://router.huggingface.co/hf-inference/models/BAAI/bge-m3/pipeline/feature-extraction` with
`{"inputs": <text>}` and `Authorization: Bearer <HF_API_TOKEN>`.

1. **~~Exact HF endpoint + response shape/pooling for `BAAI/bge-m3`~~ — RESOLVED (measured).** The
   `/pipeline/feature-extraction` route returns a **single pooled 1024-float vector** (`list[1024] ->
   float`), **not** a per-token matrix — so **no mean-pooling** is needed and it drops into the FAISS
   `IndexFlatIP` unchanged. The returned vector is already ~unit-norm (leaf components ≈0.03), so the
   call sites' existing L2-normalize is **idempotent** on it (no conflict, per D2). **Endpoint pins:**
   MUST use the `router.huggingface.co` domain **and** the explicit `/pipeline/feature-extraction`
   suffix — the legacy `api-inference.huggingface.co` host no longer resolves, and the bare model path
   routes to a SentenceSimilarity pipeline (400, wrong).
2. **~~HF free-tier reliability for `bge-m3`~~ — RESOLVED (positive).** `bge-m3` **is served on HF's
   free tier**: probe returned HTTP 200 at ~1.2 s cold / ~0.95 s warm, no `503 model-loading`. Volume
   rate/quota caps still apply at scale → handled as a runtime degraded-run caveat (D5, EC-1/EC-2),
   **not** a blocker. `hf` is viable at $0; no pivot to Jina/Deepinfra needed.
3. **~~AC-10 merge-scope~~ — RESOLVED.** Merge is gated on the **unit ACs (AC-1..AC-9)**; **AC-10**
   (live re-eval on a HF-rebuilt index) is an **immediate post-merge measurement** (same posture as
   046's AC-9), given the Sep-2 deadline.
4. **~~HF client dependency~~ — RESOLVED → raw `httpx` (NO new dep).** The probe showed raw `httpx`
   (already a dependency) hits the router endpoint cleanly and the response needs **zero**
   post-processing (already a pooled 1024-vector), so `huggingface_hub` is unnecessary. The adapter
   hand-rolls only a `Bearer` header + bounded retry (D5) — trivial. Reverses the earlier lean toward
   the SDK, on the evidence.
5. **Provider provenance marker location (D3):** the existing `clauses_meta.jsonl` sidecar is
   **line-delimited per-clause JSON records** (no top-level object to attach a single stamp to without a
   header line), so a **sibling marker file** (e.g. `clauses.faiss.provider`) is likely the cleaner slot
   than the sidecar or FAISS index metadata. Plan-phase detail; flagged so it isn't silently omitted.
