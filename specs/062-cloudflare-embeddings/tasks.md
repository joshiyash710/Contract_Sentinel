# Feature 062 — Cloudflare Workers AI embedding provider — Implementation Tasks

Reference documents:
- Spec: `specs/062-cloudflare-embeddings/spec.md`
- Plan: `specs/062-cloudflare-embeddings/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** no node/edge/state; **§3** named config; **§7** TDD / never
  weaken a test; **§8** embedding-vs-generative model separation; **§11** branch workflow)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **Embedding seam only.** Extends the feature-050 provider seam with a 3rd branch. No LangGraph node/edge,
  no `ContractState`/`specs/001`, no migration, **no new dependency** (reuses `httpx`), no frontend.
- **Reversible:** `EMBED_PROVIDER` default stays `ollama` ⇒ local dev byte-identical. The cloudflare branch
  only runs when explicitly selected.
- **Scope allow-list (AC-8)** = `config.py`, `app/llm/embed_client.py`, `scripts/build_kb.py`,
  `app/graph/nodes/retrievers/kb_retriever.py`, `render.yaml`, the rebuilt `data/kb/*` (+`.provider`), the
  extended tests, and the 062 specs. Nothing else.
- **TDD (§7):** write each layer's tests first (httpx mocked), confirm FAIL, implement to green. Never weaken.
- **§8:** the Cloudflare client serves ONLY `@cf/baai/bge-m3` (embedding); never a generative model.

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create `feature/062-cloudflare-embeddings`
  (`git-start`). Commit the APPROVED spec/plan/tasks on the branch.

**Verify:** `git branch --show-current` → `feature/062-cloudflare-embeddings`.

---

## Task 1: `config.py` — CF_* constants + validate guard  [AC-6]
- [ ] Update the `EMBED_PROVIDER` comment to `"ollama" | "hf" | "cloudflare"` (value parsing unchanged).
- [ ] Near the `HF_*` block add: `CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")`,
  `CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")` (secret — NEVER logged),
  `CF_EMBED_MODEL = os.getenv("CF_EMBED_MODEL", "@cf/baai/bge-m3")`,
  `CF_EMBED_MAX_RETRIES = _env_int("CF_EMBED_MAX_RETRIES", 2)`.
- [ ] In `validate_prod_config` (the `errs.append` function), add alongside the hf/groq/turso guards:
  `if EMBED_PROVIDER == "cloudflare" and (not CF_ACCOUNT_ID or not CF_API_TOKEN): errs.append("EMBED_PROVIDER=cloudflare but CF_ACCOUNT_ID or CF_API_TOKEN is empty")`
  (names the vars; never echoes the token).

---

## Task 2: Write the failing tests first  [AC-1..AC-7]  (httpx mocked; no network)
Extend `tests/unit/test_embed_client.py` (where the `HFEmbedClient` tests live) and
`tests/unit/test_build_kb.py` (marker tests), mirroring the 050 patterns.
- [ ] **AC-1 dispatch:** `monkeypatch.setattr(embed_client, "EMBED_PROVIDER", "cloudflare")` →
  `get_embed_client(5)` is a `CloudflareEmbedClient`; `"hf"` → `HFEmbedClient`; default/`"ollama"` →
  `ollama.Client`.
- [ ] **AC-2 request:** monkeypatch `embed_client.httpx.post` to capture args →
  `CloudflareEmbedClient(5).embeddings(prompt="x")` posts to a URL containing `CF_ACCOUNT_ID` + `CF_EMBED_MODEL`,
  header `Authorization: Bearer <CF_API_TOKEN>`, body `{"text": "x"}`.
- [ ] **AC-3 response:** a mocked 200 whose JSON is the probed Cloudflare shape → `embeddings()` returns
  `{"embedding": [<1024 floats>]}`; passing it through `embeddings.embed_query`'s real L2-normalize → unit
  vector (norm ≈ 1.0).
- [ ] **AC-4 token-safety:** force an error → assert no captured log record / exception message contains the
  `CF_API_TOKEN` value (mirror the HF token-safety test).
- [ ] **AC-5 error policy:** `httpx.RequestError` retried `CF_EMBED_MAX_RETRIES` times then raises; a non-2xx
  (402/401/500 via `raise_for_status`) raises on the FIRST attempt (assert post call count == 1); a 200 with a
  wrong-shape body → `ValueError`.
- [ ] **AC-6 guard:** with `config.EMBED_PROVIDER="cloudflare"` and empty `CF_ACCOUNT_ID` →
  `validate_prod_config` raises; both set → passes.
- [ ] **AC-7 marker:** `EMBED_PROVIDER="cloudflare"` → `build_kb._provider_marker()` ==
  `{"provider":"cloudflare","model":"@cf/baai/bge-m3"}` (JSON); and `kb_retriever._warn_on_provider_mismatch`
  on a cloudflare-marked index under a non-cloudflare active provider logs the mismatch warning (extend the
  existing marker test).
- [ ] Run `python -X utf8 -m pytest -q tests/unit/test_embed_client.py tests/unit/test_build_kb.py` →
  CONFIRM the new assertions FAIL (symbols/branches absent).

---

## Task 3: `embed_client.py` — CloudflareEmbedClient + dispatch  [AC-1..AC-5]
- [ ] Re-expose live module-level: `CF_ACCOUNT_ID = _config.CF_ACCOUNT_ID`, `CF_API_TOKEN = _config.CF_API_TOKEN`,
  `CF_EMBED_MODEL = _config.CF_EMBED_MODEL`, `CF_EMBED_MAX_RETRIES = _config.CF_EMBED_MAX_RETRIES` (bare names,
  read at call time — monkeypatchable, like the `HF_*` names).
- [ ] `_CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"`.
- [ ] `class CloudflareEmbedClient` mirroring `HFEmbedClient`:
  - `__init__(self, timeout_seconds)`: raise `ValueError` (token-safe message) if `CF_ACCOUNT_ID`/`CF_API_TOKEN`
    empty; set `self._timeout`, `self._url = _CF_URL.format(account_id=CF_ACCOUNT_ID, model=CF_EMBED_MODEL)`,
    `self._headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}`.
  - `embeddings(self, model=None, prompt="")` → `{"embedding": <list[float]>}` (ignore `model`): retry loop
    `range(CF_EMBED_MAX_RETRIES + 1)`; `httpx.post(self._url, headers=self._headers, json={"text": prompt},
    timeout=self._timeout)`; `except httpx.RequestError` → backoff+retry; `r.raise_for_status()` (non-retriable);
    parse the vector; `ValueError` on wrong shape; `return {"embedding": vec}`.
    - **Retry policy differs from `HFEmbedClient` on purpose:** only transport `httpx.RequestError` retries.
      Do NOT copy HF's 429/503 cold-start retry branch — CF's non-2xx (401/402/429/5xx) are **non-retriable**
      (a 402/429 is a deterministic quota/auth verdict; retrying can't help) → raise immediately (AC-5).
- [ ] **Response parsing (OQ-3 probe + defensive):** normalize `body["result"]["data"]` → if list-of-lists take
  `[0]`, if a flat list take as-is; fall back to `body["data"]`; else `ValueError`. **When a free CF token is
  available (Task 7), run ONE real call to confirm the exact shape** and pin it in an inline comment (mirror
  the `_HF_URL` probe note). Until then the defensive parser + AC-5 wrong-shape guard protect against drift.
- [ ] `get_embed_client`: add `if EMBED_PROVIDER == "cloudflare": return CloudflareEmbedClient(timeout_seconds)`
  BEFORE the ollama default; `"hf"`/default branches unchanged.

**Verify:** Task 2's AC-1..AC-5 tests pass.

---

## Task 4: Provider marker — 2-way → 3-way  [AC-7]
- [ ] `scripts/build_kb.py::_provider_marker` and `app/graph/nodes/retrievers/kb_retriever.py::
  _warn_on_provider_mismatch`: change the model pick from
  `HF_EMBED_MODEL if EMBED_PROVIDER=="hf" else OLLAMA_EMBED_MODEL_NAME` to a 3-way:
  `HF_EMBED_MODEL` for `"hf"`, `CF_EMBED_MODEL` for `"cloudflare"`, else `OLLAMA_EMBED_MODEL_NAME`.
  (`kb_retriever` must read `_config.CF_EMBED_MODEL`; `build_kb` reads `config.CF_EMBED_MODEL`.)

**Verify:** Task 2's AC-7 tests pass.

---

## Task 5: `render.yaml` — activate Cloudflare on the deploy
- [ ] Change inline `EMBED_PROVIDER` value `hf` → `cloudflare` (line ~18).
- [ ] Remove the embedding HF vars: `HF_EMBED_MODEL` inline (~22) and the `HF_API_TOKEN` `sync:false` secret
  (~42); add `sync:false` secrets `CF_ACCOUNT_ID` and `CF_API_TOKEN`.
- [ ] ⚠️ **Do NOT let this reach `main` until Task 7's dashboard secrets are set** — on auto-deploy,
  `EMBED_PROVIDER=cloudflare` with empty `CF_*` would hard-fail the startup guard (AC-6) and the service won't
  boot. Sequencing is enforced in Task 8.

---

## Task 6: Backend gate  [AC-1..AC-8]
- [ ] `python -X utf8 -m pytest -q` → the new/extended embed-client + marker tests pass AND the full suite
  stays green (ollama/hf paths unchanged). No network (httpx mocked). Fix code, not tests, on any surprise (§7).
- [ ] `git diff --name-only main` matches the §0 allow-list (no node/edge/`builder.py`/`ContractState`/
  `specs/001`/migration/dependency/frontend change).

---

## Task 7: Operational — Cloudflare account, rebuild the index, smoke  [AC-9]  (needs a free CF token)
- [ ] Create a free **Cloudflare account** (no card) → copy the **Account ID** + a **Workers AI API token**
  (dashboard → AI → Workers AI → *Use REST API* / API token).
- [ ] Put them in `backend/.env` (gitignored): `CF_ACCOUNT_ID=…`, `CF_API_TOKEN=…` (so the local rebuild and
  the shape-probe can authenticate without exposing the token in a command).
- [ ] **Probe** the response shape (one call) and pin it in the Task-3 parser comment.
- [ ] **Set `CF_ACCOUNT_ID` + `CF_API_TOKEN` as Render dashboard secrets NOW** (before the merge) so the
  post-merge auto-deploy boots on `cloudflare`. (Harmless while `main` still runs `hf`.)
- [ ] **Rebuild** the index via Cloudflare (build_kb already retries per-record):
  `cd backend && EMBED_PROVIDER=cloudflare .venv/Scripts/python.exe scripts/build_kb.py` → confirm the current
  corpus's vector count, dim 1024, `len(meta)==ntotal`, and the `.provider` marker says cloudflare.
- [ ] **Smoke (AC-9):** embed a known previously-flagged clause via
  `app.graph.nodes.retrievers.embeddings.embed_query(text, CRAG_EMBED_TIMEOUT_SECONDS, OLLAMA_EMBED_MODEL_NAME)`
  (routes through the cloudflare client), `search_kb(load_kb(), vec, CRAG_TOP_K)` the new index, assert top
  score ≥ `CRAG_CONFIDENCE_THRESHOLD` (0.73) — local-KB hit restored.
- [ ] Commit the rebuilt `data/kb/clauses.faiss` + `.provider` + `clauses_meta.jsonl`.

---

## Task 8: Merge
- [ ] Preconditions: Task 6 gate green; §0 diff scope; **CF dashboard secrets set (Task 7)**; the
  Cloudflare-built index committed. Only then rebase `main`, merge `feature/062-cloudflare-embeddings`, delete
  branch (`git-finish`). The auto-deploy then boots on `EMBED_PROVIDER=cloudflare` with real embeddings →
  local-KB retrieval + findings restored. $0 / no card.

---

*Per §1/§11, implementation happens only on `feature/062-cloudflare-embeddings`, opened after spec + plan +
tasks are all spec-reviewer-APPROVED. Embedding seam only — no node/edge/`ContractState`/migration/dependency/
frontend change; extends the 050 seam; default `ollama` keeps local dev byte-identical.*
