# Feature 062 — Technical plan: Cloudflare Workers AI embedding provider

Branch: `feature/062-cloudflare-embeddings` (per constitution §11).

Derived from the approved `spec.md`. Adds a third `EMBED_PROVIDER=cloudflare` branch to the feature-050
embedding seam, backed by Cloudflare Workers AI serving `@cf/baai/bge-m3` (same model as the index) on the
free, card-free tier — restoring a $0 embedding path after HF serverless went credit-gated (402). **Embedding
seam + config + the offline marker only. No node/edge/`ContractState`/migration/dependency/frontend change.**
Reversible: `EMBED_PROVIDER` default stays `ollama`.

## 0. Scope of change (files touched)
```
backend/app/config.py                                   (accept "cloudflare"; CF_* constants; validate guard)
backend/app/llm/embed_client.py                         (CloudflareEmbedClient + get_embed_client branch)
backend/scripts/build_kb.py                             (_provider_marker 2-way → 3-way)
backend/app/graph/nodes/retrievers/kb_retriever.py      (_warn_on_provider_mismatch model pick 2-way → 3-way)
render.yaml                                             (EMBED_PROVIDER=cloudflare; CF_* vars; drop HF reqs)
backend/data/kb/clauses.faiss(+.provider,+_meta.jsonl)  (REBUILT via Cloudflare — operational, Task 7)
backend/tests/unit/test_embed_client.py                 (extend: cloudflare dispatch/request/response/errors)
backend/tests/unit/test_build_kb.py                     (extend: cloudflare provider marker)  [if it asserts marker]
specs/062-cloudflare-embeddings/{spec,plan,tasks}.md
```
**NOT touched:** any LangGraph node/graph/`builder.py`; `specs/001`/`ContractState`; any Alembic migration;
`pyproject.toml`/deps (reuses `httpx`); the two bge-m3 call sites' contract (`embed_query`,
`build_kb._embed`) beyond what the seam returns; any frontend file.

## 1. `config.py` (§3, D4) — accept the provider + CF_* + guard
- `EMBED_PROVIDER` comment/union updated to `"ollama" | "hf" | "cloudflare"` (value already read via
  `os.getenv(..., "ollama").strip().lower()` — no parsing change; default unchanged).
- Add, near the `HF_*` block:
  - `CF_ACCOUNT_ID: str = os.getenv("CF_ACCOUNT_ID", "")`
  - `CF_API_TOKEN: str = os.getenv("CF_API_TOKEN", "")`  (secret — **never logged**)
  - `CF_EMBED_MODEL: str = os.getenv("CF_EMBED_MODEL", "@cf/baai/bge-m3")`
  - `CF_EMBED_MAX_RETRIES: int = _env_int("CF_EMBED_MAX_RETRIES", 2)`
- In `validate_prod_config` (the `errs.append` function), add, alongside the hf/groq/turso guards:
  ```python
  if EMBED_PROVIDER == "cloudflare" and (not CF_ACCOUNT_ID or not CF_API_TOKEN):
      errs.append("EMBED_PROVIDER=cloudflare but CF_ACCOUNT_ID or CF_API_TOKEN is empty")
  ```
  (AC-6 — message names the vars, never echoes the token.)

## 2. `embed_client.py` — CloudflareEmbedClient + dispatch (AC-1..AC-5)
- Re-expose the new config live at module scope (mirroring the bare `HF_*` names already there, "read at call
  time" so tests monkeypatch `app.llm.embed_client.CF_*`):
  `CF_ACCOUNT_ID = _config.CF_ACCOUNT_ID`, `CF_API_TOKEN = _config.CF_API_TOKEN`,
  `CF_EMBED_MODEL = _config.CF_EMBED_MODEL`, `CF_EMBED_MAX_RETRIES = _config.CF_EMBED_MAX_RETRIES`.
- `_CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"`.
- `class CloudflareEmbedClient:` mirrors `HFEmbedClient`:
  - `__init__(self, timeout_seconds)`: raise `ValueError` (token-safe message) if `CF_ACCOUNT_ID`/`CF_API_TOKEN`
    empty; set `self._timeout`, `self._url = _CF_URL.format(account_id=CF_ACCOUNT_ID, model=CF_EMBED_MODEL)`,
    `self._headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}`.
  - `embeddings(self, model=None, prompt="")` → `{"embedding": <list[float]>}` (ignore `model`; `CF_EMBED_MODEL`
    wins — same contract as `HFEmbedClient`):
    - retry loop over `range(CF_EMBED_MAX_RETRIES + 1)`; `httpx.post(self._url, headers=self._headers,
      json={"text": prompt}, timeout=self._timeout)`.
    - `except httpx.RequestError` → retriable (record, backoff `min(2**attempt, 8)`, continue).
    - `r.raise_for_status()` → a non-2xx (401/402/429/5xx) raises `HTTPStatusError` immediately (NOT retried).
    - parse the vector from the JSON (see §2.1 probe); a wrong-shape/empty body raises `ValueError`.
    - return `{"embedding": vec}`. Terminal error propagates (caller: `embed_query` → `None`; build → loud).
- `get_embed_client`: insert **before** the ollama default —
  `if EMBED_PROVIDER == "cloudflare": return CloudflareEmbedClient(timeout_seconds)`. `"hf"`/default unchanged.

### 2.1 Cloudflare response-shape probe (OQ-3 — named implementation step)
Before finalizing the parser, run ONE real call (local, with a free CF token) to capture the exact JSON:
```
POST .../ai/run/@cf/baai/bge-m3   body {"text":"a termination clause"}
```
Documented expected shape: `{"result": {"shape":[1,1024], "data": [[...1024 floats...]]}, "success": true}`
→ vector = `body["result"]["data"][0]`. The parser normalizes defensively: prefer
`body["result"]["data"]` → if it's a list-of-lists take `[0]`, if a flat list take as-is; fall back to
`body["data"]`. Record the confirmed shape in an inline comment (mirroring the `_HF_URL` probe note in
`embed_client.py`). Any unparseable shape → `ValueError` (AC-5 / EC-5).

## 3. Provider marker — 2-way → 3-way (AC-7)
Both sites currently pick the model as `HF_EMBED_MODEL if EMBED_PROVIDER=="hf" else OLLAMA_EMBED_MODEL_NAME`.
Extend to:
```python
if EMBED_PROVIDER == "hf":
    model = HF_EMBED_MODEL
elif EMBED_PROVIDER == "cloudflare":
    model = CF_EMBED_MODEL
else:
    model = OLLAMA_EMBED_MODEL_NAME
```
- `scripts/build_kb.py::_provider_marker` → stamps `{"provider":"cloudflare","model":"@cf/baai/bge-m3"}`.
- `kb_retriever.py::_warn_on_provider_mismatch` → compares the active provider/model to the index marker and
  **warns** (never fails) on mismatch — unchanged behavior, just the 3rd branch.

## 4. `render.yaml` — activate Cloudflare on the deploy
- Change the inline `EMBED_PROVIDER` value `hf` → `cloudflare` (line 18).
- Replace the HF embedding vars: drop the `HF_EMBED_MODEL` inline (line 22) and the `HF_API_TOKEN`
  `sync:false` secret (line 42) — no longer needed for embeddings; add `sync:false` secrets `CF_ACCOUNT_ID`
  and `CF_API_TOKEN` (dashboard-set). (Leave `HF_*` config constants in `config.py` — harmlessly unused unless
  a deploy re-selects `hf`.)

## 5. Tests (TDD — write first, confirm failing, then implement). `httpx` mocked; no network.
Extend `backend/tests/unit/test_embed_client.py` (where the `HFEmbedClient` tests live), mirroring them:
- **AC-1 dispatch:** `monkeypatch.setattr(embed_client, "EMBED_PROVIDER", "cloudflare")` →
  `get_embed_client(5)` is a `CloudflareEmbedClient`; `"hf"` → `HFEmbedClient`; `"ollama"`/default →
  `ollama.Client`.
- **AC-2 request:** monkeypatch `embed_client.httpx.post` to capture args → assert URL contains the account id
  + model, header `Authorization: Bearer <token>`, body `{"text": "<prompt>"}`.
- **AC-3 response:** mocked 200 whose JSON is the probed shape → `embeddings()` returns
  `{"embedding": [1024 floats]}`; feed through `embeddings.embed_query` (its real L2-normalize) → unit vector.
- **AC-4 token-safety:** force an error; assert no captured log/exception text contains the token value
  (mirror the HF token-safety test).
- **AC-5 error policy:** `httpx.RequestError` → retried `CF_EMBED_MAX_RETRIES` times then raises; a 402/401/500
  (`raise_for_status`) raises on the first attempt (assert call count == 1); a 200 wrong-shape body →
  `ValueError`.
- **AC-6 guard:** `monkeypatch` `config` to `EMBED_PROVIDER="cloudflare"`, empty `CF_ACCOUNT_ID` → the validate
  function raises; with both set → passes.
- **AC-7 marker:** `EMBED_PROVIDER="cloudflare"` → `build_kb._provider_marker()` is
  `{"provider":"cloudflare","model":"@cf/baai/bge-m3"}`; a `kb_retriever` load whose marker says cloudflare but
  active provider is ollama logs the mismatch warning (extend the existing 050 marker test).
- Run `python -X utf8 -m pytest -q tests/unit/test_embed_client.py tests/unit/test_build_kb.py` → confirm the
  new assertions FAIL first.

## 6. Correctness / constitution
- **§2/§10:** no node/edge/`ContractState`/migration — embedding seam + config + offline marker only;
  `builder.py` untouched (AC-8).
- **§3:** `EMBED_PROVIDER`/`CF_*` are named, env-overridable constants; default `ollama` ⇒ reversible/byte-
  identical (AC-1/EC-1).
- **§8:** the Cloudflare client serves ONLY the bge-m3 **embedding** model; generation (Groq/Ollama) untouched
  — model separation preserved and reinforced.
- **002:** reuses `httpx` (already a dep + used by `HFEmbedClient`); no new dependency.
- **§7:** tests written first and confirmed failing; the raw-vector/L2-normalize split stays in the call sites
  (050 invariant) — no call-site behavior weakened.

## 7. Operational: rebuild the index via Cloudflare + smoke (AC-9 — not a CI unit test)
Once §1–§5 are green, rebuild locally with a free CF token so index + query share the serving stack:
```
cd backend && EMBED_PROVIDER=cloudflare CF_ACCOUNT_ID=<id> CF_API_TOKEN=<token> \
  .venv/Scripts/python.exe scripts/build_kb.py
```
- Confirms the full corpus embeds via Cloudflare (dim 1024, `len(meta) == index.ntotal`), writes the
  `{"provider":"cloudflare",...}` marker. (`build_kb` already retries per-record — feature from the KB
  hardening — so a transient CF blip won't abort the build.)
- One-off query probe: embed a known previously-flagged clause, `search_kb` against the new index, assert the
  top score ≥ `CRAG_CONFIDENCE_THRESHOLD` (0.73) — proves the local-KB hit (and thus findings) are restored.
- Commit the rebuilt `data/kb/*` + `.provider`. Watch Cloudflare's 10k-neuron/day free cap during the build
  (~corpus size of calls; well within a day's free allotment).

## 8. Verification gate (offline)
- `python -X utf8 -m pytest -q` → the new/extended embed-client + marker tests pass AND the full suite stays
  green (ollama/hf paths unchanged). No network (httpx mocked).
- `git diff --name-only main` == the §0 allow-list (config, embed_client, build_kb, kb_retriever, render.yaml,
  the rebuilt data/kb/*, the tests, the specs). No node/edge/`ContractState`/migration/dependency/frontend.

## 9. Risks / limitations
- **Free-tier daily cap** (10k neurons/day): heavy days rate-limit → non-2xx → `embed_query` None → web
  fallback until reset (EC-3). Accepted for a $0 deploy; reversible by switching provider.
- **Cross-stack vectors:** rebuilding the index *through Cloudflare* (not reusing the Ollama-built one) removes
  any quantization/serving drift between index and query (D2) — the whole reason for Task 7.
- **CF response shape:** pinned by the §2.1 probe; the defensive parser + EC-5 guard prevent a silent bad
  vector.
- **Durability:** the index ships in the image (Dockerfile `COPY data/kb`), so no runtime storage dependency.

## 10. Merge
Full backend gate green; diff scope matches §0; the Cloudflare rebuild + 0.73 smoke confirmed. Rebase `main`,
merge `feature/062-cloudflare-embeddings`, delete branch (`git-finish`). Then the deploy step: set
`EMBED_PROVIDER=cloudflare` + `CF_ACCOUNT_ID`/`CF_API_TOKEN` in Render → redeploy → findings return.
