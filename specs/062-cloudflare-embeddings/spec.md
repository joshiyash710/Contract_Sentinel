# Feature 062 — Spec: Cloudflare Workers AI embedding provider (free bge-m3)

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/062-cloudflare-embeddings` (constitution §11).

> A third `EMBED_PROVIDER` — **`cloudflare`** — backed by **Cloudflare Workers AI** serving `@cf/baai/bge-m3`
> (the SAME model the KB index uses), on Cloudflare's **free, card-free tier**. Extends the feature-050
> embedding seam exactly like `hf` did. Motivation: HuggingFace serverless inference became credit-gated
> (returns `402` on the free tier), so the Render deploy lost working embeddings → CRAG fell back to web
> search → Self-RAG discarded all findings. Cloudflare restores a $0 embedding path. **Embedding seam only.**

## 1. Problem statement

Feature 050 established a provider seam for the BGE-M3 embedding model: `EMBED_PROVIDER` selects the client in
`app/llm/embed_client.py::get_embed_client` (`"hf"` → `HFEmbedClient`, else `ollama.Client`), used by the two
bge-m3 call sites — runtime CRAG query embedding (`embed_query`) and the offline index build
(`scripts/build_kb.py::_embed`). The Render deploy runs `EMBED_PROVIDER=hf` because Render's 512 MB free
instance cannot run Ollama.

HuggingFace has since moved serverless inference to a paid credits model: the free-tier call to
`router.huggingface.co/hf-inference/models/BAAI/bge-m3/pipeline/feature-extraction` now returns
**`402 Payment Required`** (confirmed). Consequences on the deploy: `embed_query` returns `None` for every
clause → CRAG's embedding circuit breaker opens → every clause routes to `WEB_FALLBACK` → the thin web
evidence makes Self-RAG discard findings → reports surface **no risky clauses** where they previously did.
The only free alternatives (run a model locally) do not fit Render's 512 MB.

**Cloudflare Workers AI** serves **`@cf/baai/bge-m3`** — the identical model our index is built with — on a
**free tier (10,000 Neurons/day)** whose account/token require **no credit card**. This feature adds a
`cloudflare` provider to the existing seam (one more branch + a client class mirroring `HFEmbedClient`), and
**rebuilds the KB index through Cloudflare** so the index and query vectors come from the same serving stack
(the §1 same-model/provider invariant feature 050 established).

### Position relative to the constitution
- **No LangGraph node/edge/`ContractState` change (§2).** Purely the embedding provider seam
  (`embed_client.py`) + config + the offline index-build marker. No pipeline/graph change.
- **§8 model separation honored and reinforced.** The Cloudflare client serves ONLY the bge-m3 **embedding**
  model (`@cf/baai/bge-m3`), never a generative model. Generation stays on Groq/Ollama, untouched.
- **§3 configurable.** New named config constants (`EMBED_PROVIDER="cloudflare"`, `CF_*`), env-overridable;
  `CF_API_TOKEN` is a secret — **never logged** (mirrors the `HF_API_TOKEN` handling).
- **Extends feature 050, no amendment needed.** 050 already made `EMBED_PROVIDER` a multi-provider seam; this
  adds a provider within that established design. No new dependency — reuses `httpx` (as `HFEmbedClient` does),
  so no 002-tech-stack change.
- **Reversible.** `EMBED_PROVIDER=ollama` (default) is byte-identical to today; the `cloudflare` branch only
  runs when explicitly selected.

## 2. Inputs and outputs

### New config (§3) — `app/config.py`
- `EMBED_PROVIDER` now accepts `"cloudflare"` (alongside `"ollama"`/`"hf"`; default stays `"ollama"`).
- `CF_ACCOUNT_ID: str = os.getenv("CF_ACCOUNT_ID", "")` — Cloudflare account id (part of the API URL).
- `CF_API_TOKEN: str = os.getenv("CF_API_TOKEN", "")` — Workers AI API token (Bearer). **Never logged.**
- `CF_EMBED_MODEL: str = os.getenv("CF_EMBED_MODEL", "@cf/baai/bge-m3")` — the Workers AI model slug.
- `CF_EMBED_MAX_RETRIES: int = _env_int("CF_EMBED_MAX_RETRIES", 2)` — mirrors `HF_EMBED_MAX_RETRIES`.
- **Startup guard:** the config validate adds
  `if EMBED_PROVIDER == "cloudflare" and (not CF_ACCOUNT_ID or not CF_API_TOKEN): errs.append(...)` — fail
  fast with a clear message (mirrors the `hf`/`groq`/`turso` guards), never echoing the token.

### New client — `app/llm/embed_client.py`
- `CloudflareEmbedClient` mimics `ollama.Client`'s `.embeddings(model=…, prompt=…) -> {"embedding": [...]}`
  (same shape `HFEmbedClient` returns), so the two call sites and `embed_query`'s `resp["embedding"]`
  handling are unchanged. It POSTs the clause text to the Workers AI run endpoint
  `https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_EMBED_MODEL}` with
  `Authorization: Bearer {CF_API_TOKEN}`, parses the embedding vector out of the response, and returns
  `{"embedding": <list[float]>}`. Retries only transport errors (`httpx.RequestError`) with bounded backoff;
  a non-retriable HTTP status (`raise_for_status`) or a wrong-shape 200 body raises immediately — identical
  error policy to `HFEmbedClient`. **The exact request/response JSON shape is confirmed by a probe during
  implementation** (plan/tasks), mirroring the documented HF-URL probe note; the adapter normalizes whatever
  Workers AI returns (`result.data[0]` / `result.data` / `data`) into the flat float list.
- `get_embed_client`: add `if EMBED_PROVIDER == "cloudflare": return CloudflareEmbedClient(timeout_seconds)`
  before the ollama default. `"hf"`/default branches unchanged.
- The returned vector stays **raw** (not normalized); L2-normalization remains in the call sites
  (`embed_query` / `build_kb._embed`), exactly as for ollama/hf (050 invariant). bge-m3 is 1024-dim ⇒ matches
  `EMBED_DIM=1024`, so the existing index geometry is unchanged.

### Provider marker (050 D3) — `app/graph/nodes/retrievers/kb_retriever.py` + `scripts/build_kb.py`
- `build_kb._provider_marker` and `kb_retriever._warn_on_provider_mismatch` currently pick the model name as
  `HF_EMBED_MODEL if EMBED_PROVIDER=="hf" else OLLAMA_EMBED_MODEL_NAME`. Extend both to a 3-way choice so
  `cloudflare` stamps/compares `{"provider":"cloudflare","model":CF_EMBED_MODEL}`. A Cloudflare-built index
  queried under a different provider then correctly warns (meaningless cosine), per 050.

### The KB index — rebuilt via Cloudflare
- Rebuild `data/kb/clauses.faiss` (+ `clauses_meta.jsonl` + `.provider`) with `EMBED_PROVIDER=cloudflare`
  (`scripts/build_kb.py`, which already routes through `get_embed_client`), so index vectors and runtime query
  vectors come from the **same** Cloudflare bge-m3 serving stack. The rebuilt `.provider` marker reads
  `{"provider":"cloudflare","model":"@cf/baai/bge-m3"}`. Shipped in the image (Dockerfile `COPY data/kb`).

### Deploy config (operational, documented not committed as secrets)
- Render env to activate: `EMBED_PROVIDER=cloudflare`, `CF_ACCOUNT_ID=…`, `CF_API_TOKEN=…` (dashboard secret).
  `render.yaml`'s inline `EMBED_PROVIDER=hf` is updated to `cloudflare`; `HF_API_TOKEN` no longer required.

### Resolved decisions (inline)
- **D1 — Cloudflare over Gemini/Jina.** Only Cloudflare serves the SAME model (bge-m3) on a free, card-free
  tier, minimizing change and keeping the index geometry; other free APIs are different models.
- **D2 — Rebuild the index via Cloudflare** (not reuse the Ollama-built one) to honor the 050 same-serving-
  stack invariant; cross-stack numeric drift (quantized Ollama vs Cloudflare) is avoided.
- **D3 — Same return contract.** `CloudflareEmbedClient.embeddings` returns `{"embedding": [...]}`; no call-
  site change beyond the seam.
- **D4 — Reversible, default off.** `EMBED_PROVIDER` default stays `ollama`; local dev byte-identical.

## 3. Acceptance criteria

Backend, offline (pytest; `httpx` mocked — no network). Mirrors the feature-050 `HFEmbedClient` test approach.

- **AC-1 (provider selection):** with `EMBED_PROVIDER="cloudflare"`, `get_embed_client(t)` returns a
  `CloudflareEmbedClient`; `"hf"` still returns `HFEmbedClient`; default/`"ollama"` still returns
  `ollama.Client` (byte-identical).
- **AC-2 (request shape):** `CloudflareEmbedClient(...).embeddings(model=…, prompt="x")` issues one
  `httpx.post` to `…/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_EMBED_MODEL}` with an `Authorization: Bearer
  {CF_API_TOKEN}` header and the clause text in the body (mocked transport asserts URL + header + body).
- **AC-3 (response → {"embedding": …}):** a mocked 200 Workers AI body yields `{"embedding": <1024-float
  list>}`; `embed_query` then L2-normalizes it to a unit vector (norm ≈ 1.0), exactly as for hf/ollama.
- **AC-4 (token never logged):** on error, no log record or exception message contains `CF_API_TOKEN`
  (assert on captured logs), mirroring the HF client's token-safety test.
- **AC-5 (error policy):** a transport error (`httpx.RequestError`) retries up to `CF_EMBED_MAX_RETRIES`; a
  non-2xx status (e.g. 401/402/500) raises immediately (no retry); a 200 with a wrong-shape body raises — so
  `embed_query` turns any failure into `None` (clause → web fallback) and the offline build fails loudly.
- **AC-6 (startup guard):** `EMBED_PROVIDER=cloudflare` with an empty `CF_ACCOUNT_ID` or `CF_API_TOKEN` makes
  the config validate raise the clear fail-fast error; with both set it passes.
- **AC-7 (provider marker):** building with `cloudflare` writes `{"provider":"cloudflare","model":
  "@cf/baai/bge-m3"}`; `kb_retriever._warn_on_provider_mismatch` warns (not fails) when the active provider
  differs from the index marker, and is silent when they match.
- **AC-8 (no architecture change):** `git diff main` touches only `app/config.py`, `app/llm/embed_client.py`,
  `app/graph/nodes/retrievers/kb_retriever.py` (marker 3-way), `scripts/build_kb.py` (marker 3-way),
  `render.yaml`, the rebuilt `data/kb/*` (+ `.provider`), the new tests, and the 062 specs. No node/edge/
  `ContractState`/`specs/001`/migration/dependency/frontend change. Full backend suite green.
- **AC-9 (live rebuild + smoke — operational, not a unit test):** `EMBED_PROVIDER=cloudflare CF_ACCOUNT_ID=…
  CF_API_TOKEN=… python scripts/build_kb.py` builds an index via Cloudflare with **the current corpus's vector
  count, dim 1024** (`len(meta) == index.ntotal`); a one-off query probe confirms a known risky clause scores
  ≥ the 0.73 threshold against it (local-KB hit restored).

## 4. Edge cases
- **EC-1 — Default/ollama/hf unchanged:** `EMBED_PROVIDER` unset or `ollama`/`hf` → the cloudflare branch is
  never constructed; byte-identical to today (AC-1).
- **EC-2 — Cloudflare 401/403 (bad token/account):** non-retriable → raises → `embed_query` returns `None` →
  clause routes to web fallback (graceful), and the offline build fails loudly with a non-token message.
- **EC-3 — Free-tier daily quota exhausted (429/limit):** treated like any non-2xx → `None` at runtime → web
  fallback until the quota resets; no crash. Documented as the accepted free-tier limit.
- **EC-4 — Transient transport error (timeout/reset):** retried up to `CF_EMBED_MAX_RETRIES`, then `None`
  (runtime) / loud failure (build) — same as hf.
- **EC-5 — Wrong-shape / empty 200 body:** raises (no silent zero vector); `embed_query` → `None`.
- **EC-6 — Zero-norm vector:** the call sites' existing `norm < 1e-12` guard rejects it (unchanged).
- **EC-7 — Index/provider mismatch after switching:** if the shipped index is Cloudflare-built but the deploy
  runs a different provider (or vice-versa), `_warn_on_provider_mismatch` logs the 050 warning; retrieval
  still runs (scores just unreliable) — oper/ops signal, not a crash.
- **EC-8 — Batch vs single input:** the call sites embed one clause per call (`prompt=text`); the adapter
  sends a single text and reads the single returned vector (no batching introduced).

## 5. Out of scope
- **Any generative (LLM) provider change** — generation stays Groq/Ollama; this is the embedding seam only (§8).
- **Batching multiple clauses per request** — one-text-per-call preserves the existing call-site contract;
  batching is a possible later optimization.
- **A new dependency** — reuses `httpx`; no SDK added.
- **Changing the embedding model/dimension** — stays bge-m3 / 1024-dim, so the index geometry and `EMBED_DIM`
  are unchanged.
- **Any LangGraph node/edge/`ContractState`/migration/frontend change.**
- **Auto-failover between providers** (e.g., cloudflare→hf on quota) — single configured provider per deploy.

## 6. Evaluation (metrics to log)
This restores the embedding path that feeds CRAG's 0.73 routing, so retrieval is the thing to verify:
- **AC-9 operational smoke:** after the Cloudflare rebuild, confirm a known previously-flagged clause scores
  **≥ 0.73** against the new index (local-KB hit), i.e. the regression that sent everything to web fallback is
  reversed. Optionally record the LOCAL_KB-vs-WEB_FALLBACK split on a sample contract before/after.
- **Guardrail:** a Cloudflare-built index queried under Cloudflare must reproduce the same
  inner-product == cosine behavior (vectors L2-normalized on both sides); the negative case (provider marker
  mismatch) must still only **warn**, never crash (AC-7). No CRAG/Self-RAG eval-harness change.

## 7. Open questions

Resolved inline (2026-10-08); none architecturally significant remains:
- **OQ-1 — Which free provider? → RESOLVED: Cloudflare Workers AI** (D1) — same model (bge-m3), free/card-free,
  minimal change, no index-geometry shift.
- **OQ-2 — Reuse or rebuild the index? → RESOLVED: rebuild via Cloudflare** (D2) — same-serving-stack invariant.
- **OQ-3 — Exact Workers AI request/response JSON shape → RESOLVED by a probe during implementation** (the
  adapter normalizes the vector out of the documented `result.data` shape; the plan pins the probe step, as
  feature 050 did for the HF URL). This is a transport detail, not an architectural unknown.

No open questions remain.
