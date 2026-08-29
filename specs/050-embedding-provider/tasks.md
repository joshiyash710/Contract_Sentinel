# Feature 050 — Tasks: Embedding provider adapter (HuggingFace bge-m3, Ollama default)

Implements `specs/050-embedding-provider/plan.md` (spec + plan spec-reviewer-APPROVED). TDD per
constitution §7: write/adjust tests and confirm them FAILING before implementing; never weaken a test to
force a pass. All unit tests are offline — **`httpx` is mocked, no network**. Run from `backend/`.

Traceability: each task cites the acceptance criterion (AC-n) from `spec.md` it satisfies.

---

## T0 — Preconditions (no code change)
0.1 Confirm current branch is `feature/050-embedding-provider` (`git branch --show-current`).
0.2 **Revert any local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b override** in `backend/.env` / environment
    before running `test_config` (a local qwen3:4b override breaks existing config asserts). Re-apply
    after merge if desired for low-RAM local runs.
0.3 `HF_API_TOKEN` is already set in gitignored `backend/.env` (used only by AC-10 live measurement /
    manual runs; **unit tests mock httpx and need no token**).
0.4 Baseline: `python -m pytest -q` is green before starting.

## T1 — (TEST FIRST) config asserts — AC-7
1.1 In `tests/unit/test_config.py`, add asserts:
    - `EMBED_PROVIDER` default `"ollama"` and value ∈ {`"ollama"`, `"hf"`}.
    - `HF_EMBED_MODEL` is a non-empty `str` (default `"BAAI/bge-m3"`).
    - `HF_EMBED_MAX_RETRIES` is an `int`.
    - `EMBED_DIM` is an `int` equal to `1024`.
1.2 Run `python -m pytest tests/unit/test_config.py -q` → **confirm FAIL** (constants don't exist yet).

## T2 — (IMPL) config constants — AC-7
2.1 In `app/config.py`, near `OLLAMA_EMBED_MODEL_NAME` (~line 221), add (env-read; `load_dotenv()` is
    ALREADY present from feature 046 — do NOT re-add):
    ```python
    EMBED_PROVIDER: str = os.getenv("EMBED_PROVIDER", "ollama").strip().lower()   # "ollama" | "hf"
    HF_API_TOKEN: str = os.getenv("HF_API_TOKEN", "")
    HF_EMBED_MODEL: str = os.getenv("HF_EMBED_MODEL", "BAAI/bge-m3")
    HF_EMBED_MAX_RETRIES: int = _env_int("HF_EMBED_MAX_RETRIES", 2)
    EMBED_DIM: int = _env_int("EMBED_DIM", 1024)   # bge-m3 vector length (AC-8 shape guard)
    ```
    Comment: default `ollama` ⇒ byte-for-byte today; `hf` routes EMBEDDINGS to HF (generation seam,
    feature 046, is separate — §8). **Do NOT log `HF_API_TOKEN`.**
2.2 Run `tests/unit/test_config.py -q` → **green**.

## T3 — (TEST FIRST) adapter unit tests — AC-1,2,3,4,6,8
3.1 Create `tests/unit/test_embed_client.py`. Mock `app.llm.embed_client.httpx.post` (a helper returning
    a fake response with `.status_code`, `.json()`, `.raise_for_status()`); monkeypatch the bare
    module-level `EMBED_PROVIDER`/`HF_API_TOKEN`/`HF_EMBED_MODEL`/`HF_EMBED_MAX_RETRIES`/`EMBED_DIM` for
    each case. Tests:
    - **AC-1:** `get_embed_client(5)` → `ollama.Client` when `EMBED_PROVIDER="ollama"`; `HFEmbedClient`
      when `"hf"` (with a stub token).
    - **AC-2:** mocked 200 body = `[0.1]*EMBED_DIM` → `HFEmbedClient(5).embeddings(model="bge-m3",
      prompt="x")` returns `{"embedding": [0.1]*EMBED_DIM}`; assert the POST url contains `HF_EMBED_MODEL`
      and the ending `/pipeline/feature-extraction`, and `json={"inputs":"x"}`.
    - **AC-3 (§8):** the POST always targets `HF_EMBED_MODEL` regardless of the `model=` arg passed;
      assert the URL never contains a generative model name.
    - **AC-4 (failure raises out of adapter):** (a) `httpx.post` raises `httpx.ConnectError` on every
      attempt → `.embeddings()` raises after `HF_EMBED_MAX_RETRIES`; (b) persistent `status_code=503` →
      raises after retries; (c) `raise_for_status` raising `HTTPStatusError` → raises immediately (assert
      httpx.post called once, not retried); (d) wrong-shape 200 body (wrong len / nested list) →
      `ValueError` raised immediately (called once). (The runtime→None behavior is asserted in T5/AC-4.)
    - **AC-6:** missing `HF_API_TOKEN` + `EMBED_PROVIDER="hf"` → `ValueError` at construction whose
      message does NOT contain the token; assert the token string appears in no exception message.
    - **AC-8:** correct `EMBED_DIM`-length flat list passes; a `EMBED_DIM+1` list and a nested
      `[[...]]` are rejected (`ValueError`).
3.2 Run `python -m pytest tests/unit/test_embed_client.py -q` → **confirm FAIL** (module doesn't exist).

## T4 — (IMPL) adapter — AC-1,2,3,4,6,8
4.1 Create `app/llm/embed_client.py` exactly per plan §2: module docstring (embedding seam, separate
    from the 046 generation seam, HF path serves only `bge-m3`, token never logged); bare module-level
    config names (read at call time, for monkeypatch); `_HF_URL` router template with the pinned
    `/pipeline/feature-extraction` path; `_backoff(attempt)`; `_dim(vec)` (token-free shape descriptor);
    `HFEmbedClient` (token-empty → `ValueError`; `.embeddings()` retry loop where ONLY
    `httpx.RequestError` is retried, `raise_for_status` + shape `ValueError` propagate immediately;
    returns `{"embedding": raw_list}`); `get_embed_client(timeout_seconds)` factory.
4.2 Do NOT touch `chat_client.py`. `app/llm/__init__.py` already exists (feature 035).
4.3 Run `tests/unit/test_embed_client.py -q` → **green**.

## T5 — (TEST FIRST) runtime wire-in tests — AC-4, AC-5 (runtime site)
5.1 In `tests/unit/test_embeddings.py`, **update the patch target** from
    `app.graph.nodes.retrievers.embeddings.ollama.Client` to
    `app.graph.nodes.retrievers.embeddings.get_embed_client` (return the existing `MagicMock` client
    whose `.embeddings()` returns `{"embedding": [...]}`). This is a patch-target update because the
    client construction legitimately moves to `embed_client.py`; the existing normalization / model
    assertions are UNCHANGED (not weakened, per §7).
5.2 Add:
    - **AC-5 (default ollama, runtime):** with `EMBED_PROVIDER="ollama"`, `embed_query(...)` still works
      via `get_embed_client` returning an `ollama.Client` (spy: assert `get_embed_client` called with the
      passed `timeout_seconds`).
    - **AC-4 (HF failure → None):** with a `get_embed_client` returning a client whose `.embeddings()`
      raises (`httpx.ConnectError` / `ValueError` shape) → `embed_query(...)` returns `None` and does not
      raise (feeds the circuit breaker). A zero-norm vector also → `None` (keep/confirm existing).
5.3 Run `tests/unit/test_embeddings.py -q` → **confirm FAIL** (embeddings.py not yet swapped /
    `get_embed_client` not importable there).

## T6 — (IMPL) runtime wire-in — AC-4, AC-5
6.1 In `app/graph/nodes/retrievers/embeddings.py::_call_embed`, replace
    `client = ollama.Client(timeout=timeout_seconds)` with `client = get_embed_client(timeout_seconds)`;
    add `from app.llm.embed_client import get_embed_client` at module level. Leave the
    `client.embeddings(model=model_name, prompt=text)` call, the dict/pydantic response handling, the
    zero-norm guard, the L2-normalization, and the surrounding `try/except Exception: return None`
    UNCHANGED. Remove the now-unused `import ollama` only if `ruff` flags it.
6.2 Run `tests/unit/test_embeddings.py -q` and `tests/unit/test_crag_retrieval_agent.py -q` → **green**.

## T7 — (TEST FIRST) build_kb wire-in + provenance — AC-5 (offline site), AC-8
7.1 Add `tests/unit/test_build_kb.py` (or extend an existing build_kb test if present):
    - **AC-5 (default ollama, offline):** `scripts.build_kb._embed("x")` routes through
      `get_embed_client` (patch `scripts.build_kb.get_embed_client` to a mock returning
      `{"embedding": [...]}`); assert it reads `resp["embedding"]` and returns a normalized vector.
    - **AC-8 (offline raises):** a wrong-shape adapter result makes `_embed` raise (loud offline
      failure, not a silently corrupt index).
    - **Provenance write:** after the index build, `build_kb` writes a sibling `clauses.faiss.provider`
      file containing the active provider + embed model (test the small marker-writer helper directly to
      avoid running the full corpus build).
7.2 Run → **confirm FAIL**.

## T8 — (IMPL) build_kb wire-in + provenance marker — AC-5, AC-8, D3
8.1 In `scripts/build_kb.py::_embed`, replace `ollama.embeddings(model=config.OLLAMA_EMBED_MODEL_NAME,
    prompt=text)` with `get_embed_client(config.CRAG_EMBED_TIMEOUT_SECONDS).embeddings(
    model=config.OLLAMA_EMBED_MODEL_NAME, prompt=text)`; add the import. Keep `resp["embedding"]`, the
    internal L2-normalization, and the `OLLAMA_EMBED_MODEL_NAME != OLLAMA_MODEL_NAME` guard.
8.2 After `faiss.write_index(...)` in `main()`, write the sibling marker
    `Path(str(index_path) + ".provider")` = `json.dumps({"provider": config.EMBED_PROVIDER, "model":
    <HF_EMBED_MODEL if hf else OLLAMA_EMBED_MODEL_NAME>})`. Factor the marker string into a tiny helper
    so T7 can unit-test it without a full build.
8.3 Run `tests/unit/test_build_kb.py -q` → **green**.

## T9 — (TEST FIRST) provenance-mismatch warning — D3/EC-7
9.1 In `tests/unit/test_kb_retriever.py`, add: `load_kb()` emits a single `logger.warning` when a
    sibling `.provider` marker disagrees with the active `EMBED_PROVIDER`/embed model, and emits NO such
    warning when the marker matches or is absent. (Use the existing test's index/marker fixtures; assert
    via `caplog`.) Behavior otherwise unchanged (still returns the loaded KB).
9.2 Run → **confirm FAIL**.

## T10 — (IMPL) provenance-mismatch warning — D3/EC-7
10.1 In `app/graph/nodes/retrievers/kb_retriever.py::load_kb`, right after the successful
     `faiss.read_index(...)` (~line 70), read the sibling `str(index_path) + ".provider"` marker if it
     exists; if its `provider`/`model` disagrees with the active `EMBED_PROVIDER`/embed model, emit one
     `logger.warning(...)` in the existing style (lines ~57-66). **Warning only** — a missing marker is
     tolerated silently; a mismatch warns but `load_kb` still returns the KB (no behavior change).
10.2 Run `tests/unit/test_kb_retriever.py -q` → **green**.

## T11 — Full suite + diff-scope gate — AC-9
11.1 `python -m pytest -q` → whole suite **green**.
11.2 `ruff check .` and `black --check .` clean on the touched files.
11.3 `git diff --name-only main` equals the plan §0 allow-list ONLY:
     `app/config.py`, `app/llm/embed_client.py` (NEW), `app/graph/nodes/retrievers/embeddings.py`,
     `app/graph/nodes/retrievers/kb_retriever.py`, `scripts/build_kb.py`,
     `tests/unit/test_embed_client.py` (NEW), `tests/unit/test_config.py`,
     `tests/unit/test_embeddings.py`, `tests/unit/test_kb_retriever.py`,
     `tests/unit/test_build_kb.py` (NEW if added), `specs/050-embedding-provider/*`.
     **NO** `pyproject.toml`/`uv.lock` change (no new dep); **NO** graph/edge/`ContractState`/migration/
     generation/frontend change; **`OLLAMA_MODEL_NAME` unchanged** (qwen3:8b).

## T12 — Merge (git-finish) — deferred: AC-10
12.1 Ensure T11 green + diff-scope clean + `OLLAMA_MODEL_NAME` reverted. Rebase `main`, merge
     `feature/050-embedding-provider`, delete branch (`git-finish`). Re-apply local qwen3:4b override
     afterward if desired.
12.2 **AC-10 (post-merge, live — NOT a merge blocker):** with `EMBED_PROVIDER=hf` + `HF_API_TOKEN`,
     rebuild the index (`EMBED_PROVIDER=hf python scripts/build_kb.py`), run
     `python -X utf8 -m eval.harness.run` + `score` on the 046 AC-9 gold subset, and record retrieval
     hit-rate / recall / precision / false-flag vs the Ollama baseline in a `RESULTS.md`. Add the
     `EMBED_PROVIDER=hf … build_kb` rebuild note + provider-parity operator duty to `docs/DEPLOYMENT.md`
     alongside this measurement (kept out of the gated merge diff to preserve AC-9 scope).

---

### Notes for the implementation model
- The adapter reads config via **bare module-level names** (`EMBED_PROVIDER = _config.EMBED_PROVIDER`,
  etc.) so tests monkeypatch `app.llm.embed_client.<NAME>` — mirror `app/llm/chat_client.py` exactly.
- **Never log or embed `HF_API_TOKEN`** in any message; it lives only in the `Authorization` header.
- The HF 200 body IS the pooled 1024-float list (measured 2026-08-29) — no pooling/reshaping; just
  validate length == `EMBED_DIM` and return it raw under `{"embedding": ...}`.
- Do not touch the generation seam (`chat_client.py`) or any generative node (§8).
