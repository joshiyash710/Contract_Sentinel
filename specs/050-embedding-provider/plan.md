# Feature 050 — Technical plan: Embedding provider adapter (HuggingFace bge-m3, Ollama default)

Branch: `feature/050-embedding-provider` (per constitution §11).

Derived from `spec.md` (spec-reviewer-APPROVED; all 5 open questions resolved by the 2026-08-29 HF probe).
Adds an **embedding** provider seam — the direct analog of feature 046's generation seam. The two
`bge-m3` embedding call sites route through a factory that returns either today's `ollama.Client`
(default) or an `HFEmbedClient` that mimics Ollama's `.embeddings(model, prompt) -> {"embedding": [...]}`
shape, backed by the HuggingFace Inference API. **No graph/edge/`ContractState`/migration change; no new
dependency** (raw `httpx`, already a dep). The generation seam (`chat_client.py`) is untouched (§8).

## 0. Scope of change (files touched)

Per **AC-9** the `git diff --name-only main` must show only:
```
backend/app/config.py                                     (5 new §3 constants; load_dotenv already present)
backend/app/llm/embed_client.py                           (NEW — get_embed_client + HFEmbedClient, httpx)
backend/app/graph/nodes/retrievers/embeddings.py          (1-line client swap in _call_embed)
backend/app/graph/nodes/retrievers/kb_retriever.py        (D3 provenance-mismatch WARNING at index load)
backend/scripts/build_kb.py                               (1-line swap in _embed + write provenance marker)
backend/tests/unit/test_embed_client.py                   (NEW — AC-1..AC-8, httpx MOCKED)
backend/tests/unit/test_config.py                         (AC-7)
backend/tests/unit/test_embeddings*.py / test_kb_retriever*.py (AC-4/AC-5/provenance, as needed)
specs/050-embedding-provider/{spec,plan,tasks}.md
```
- **NO `pyproject.toml`/`uv.lock` change** (OQ#4 resolved → raw `httpx`, already a dependency).
- **`chat_client.py` and every generative node are NOT touched** (§8 — this is the embedding seam only).
- `app/llm/__init__.py` already exists (feature 035) — no new package marker.
- **⚠ Revert any local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b override before committing** (breaks
  `test_config` asserts); re-apply after merge for local low-RAM runs.

## 1. Config (`app/config.py`)

- **`load_dotenv()` is already at the top of `config.py` (feature 046) — do NOT re-add.** `HF_API_TOKEN`
  from `backend/.env` is therefore already loadable.
- **New constants** (near `OLLAMA_EMBED_MODEL_NAME`, line ~221, env-read):
  ```python
  EMBED_PROVIDER: str = os.getenv("EMBED_PROVIDER", "ollama").strip().lower()   # "ollama" | "hf"
  HF_API_TOKEN: str = os.getenv("HF_API_TOKEN", "")
  HF_EMBED_MODEL: str = os.getenv("HF_EMBED_MODEL", "BAAI/bge-m3")
  HF_EMBED_MAX_RETRIES: int = _env_int("HF_EMBED_MAX_RETRIES", 2)
  EMBED_DIM: int = _env_int("EMBED_DIM", 1024)   # bge-m3 vector length; AC-8 shape guard
  ```
  Comment: default `ollama` ⇒ byte-for-byte today; `hf` routes **embeddings** to the HF Inference API
  (the generation seam, feature 046, is separate — §8). **Do NOT log `HF_API_TOKEN`.**
- `EMBED_DIM` is a §3 named constant (AC-8): the adapter validates the returned vector length against it
  (resolves the spec-reviewer's AC-8 note — a named constant, not a magic `1024`).

## 2. Adapter (`app/llm/embed_client.py`, NEW)

```python
"""Embedding provider seam (feature 050). get_embed_client() returns an Ollama client (default) or an
HFEmbedClient that mimics ollama.Client.embeddings' (model, prompt) -> {"embedding": [...]} shape, so the
two bge-m3 call sites swap ONE line. This is the EMBEDDING seam, separate from the generation seam
(feature 046, chat_client.py); the HF path ONLY ever serves bge-m3 embeddings, never a generative model
(constitution §8). HF_API_TOKEN is never logged."""
import time
import httpx
import ollama
import app.config as _config

# Bare module names (read at call time) so tests can monkeypatch them, mirroring chat_client.py.
EMBED_PROVIDER = _config.EMBED_PROVIDER
HF_API_TOKEN = _config.HF_API_TOKEN
HF_EMBED_MODEL = _config.HF_EMBED_MODEL
HF_EMBED_MAX_RETRIES = _config.HF_EMBED_MAX_RETRIES
EMBED_DIM = _config.EMBED_DIM

# OQ#1 probe (2026-08-29): the router domain + explicit /pipeline/feature-extraction path returns a
# single pooled EMBED_DIM-float vector. Legacy api-inference.huggingface.co no longer resolves; the bare
# model path routes to SentenceSimilarity (400). Do NOT change this URL shape without re-probing.
_HF_URL = "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"


def _backoff(attempt: int) -> float:
    return min(2.0 ** attempt, 8.0)   # 1s, 2s, 4s… bounded (D5)


def _dim(vec) -> object:
    """Token-free shape descriptor for error messages (never echoes the token)."""
    return len(vec) if isinstance(vec, list) else type(vec).__name__


class HFEmbedClient:
    """Mimics ollama.Client for the .embeddings(model, prompt) call the two sites make."""
    def __init__(self, timeout_seconds: float):
        if not HF_API_TOKEN:
            raise ValueError(
                "EMBED_PROVIDER=hf but HF_API_TOKEN is empty — set it in backend/.env "
                "(see docs/DEPLOYMENT.md). (token value intentionally not shown)"
            )
        self._timeout = float(timeout_seconds)
        self._url = _HF_URL.format(model=HF_EMBED_MODEL)   # HF_EMBED_MODEL wins; embedding model only
        self._headers = {"Authorization": f"Bearer {HF_API_TOKEN}",
                         "Content-Type": "application/json"}

    def embeddings(self, model=None, prompt=""):
        """Ignore `model` (HF_EMBED_MODEL wins); return {"embedding": <raw EMBED_DIM-float list>}.

        Only transport errors (timeout / connection / retriable 503|429) are retried; a deterministic
        error (non-retriable HTTP status, or a wrong-shape 200 body) raises immediately — retrying it
        cannot help (spec-reviewer suggestion 1)."""
        last_exc = None
        for attempt in range(HF_EMBED_MAX_RETRIES + 1):
            try:
                r = httpx.post(self._url, headers=self._headers,
                               json={"inputs": prompt}, timeout=self._timeout)
            except httpx.RequestError as e:  # retriable transport failure (timeout/connection/transport)
                last_exc = e
                if attempt < HF_EMBED_MAX_RETRIES:
                    time.sleep(_backoff(attempt)); continue
                raise
            if r.status_code in (503, 429) and attempt < HF_EMBED_MAX_RETRIES:
                time.sleep(_backoff(attempt)); continue            # cold-start / rate-limit (EC-1/EC-2)
            r.raise_for_status()                                    # other 4xx/5xx → raise (not retried)
            vec = r.json()
            if (not isinstance(vec, list) or len(vec) != EMBED_DIM
                    or (vec and isinstance(vec[0], list))):
                raise ValueError(f"unexpected HF embedding shape (dim={_dim(vec)})")  # no token; not retried
            return {"embedding": vec}                               # RAW; caller L2-normalizes (D2)
        raise last_exc   # retries exhausted on a transport error


def get_embed_client(timeout_seconds: float):
    """Factory: ollama.Client (default) or HFEmbedClient, per EMBED_PROVIDER (read live)."""
    if EMBED_PROVIDER == "hf":
        return HFEmbedClient(timeout_seconds)
    return ollama.Client(timeout=timeout_seconds)
```
- **Token never logged (AC-6):** the missing-token error and the shape-error message never include the
  token; the token lives only in the `Authorization` header (never in the URL, never in exception text).
  `httpx.HTTPStatusError` echoes URL+status, not headers.
- **Return RAW vector (D2):** the caller's existing L2-normalize applies. The HF vector is already
  ~unit-norm (probe) so normalizing is idempotent — no double-normalization issue.
- **Shape guard (AC-8):** rejects anything that isn't a flat `EMBED_DIM`-length list → `ValueError`,
  which `_call_embed` turns into `None` (runtime) and `build_kb` lets propagate (loud offline failure).
- **`_dim(vec)`** helper: best-effort shape descriptor for the error message (never the token).

## 3. Wire-in (2 embedding sites — the only functional edits)

**3.1 `app/graph/nodes/retrievers/embeddings.py::_call_embed`** — replace the client construction only:
```python
# before:  client = ollama.Client(timeout=timeout_seconds)
from app.llm.embed_client import get_embed_client      # module-level import
client = get_embed_client(timeout_seconds)
```
Everything else is unchanged: `client.embeddings(model=model_name, prompt=text)`, the dict/pydantic
response handling, the zero-norm guard, the L2-normalization, and — critically — the surrounding
`try/except Exception: return None`. An `HFEmbedClient` failure (timeout/HTTP/retry-exhausted/shape)
raises out of `.embeddings(...)` and is caught by that existing handler → `None` → feeds
`CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD` exactly as an Ollama failure does today (AC-4). The `httpx`
timeout is bound by the passed `timeout_seconds`; the existing ThreadPoolExecutor backstop
(`timeout_seconds + 5`) still applies.

**3.2 `scripts/build_kb.py::_embed`** — swap the module-level `ollama.embeddings(...)` for the factory:
```python
# before:  resp = ollama.embeddings(model=config.OLLAMA_EMBED_MODEL_NAME, prompt=text)
from app.llm.embed_client import get_embed_client
resp = get_embed_client(config.CRAG_EMBED_TIMEOUT_SECONDS).embeddings(
    model=config.OLLAMA_EMBED_MODEL_NAME, prompt=text)
```
`resp["embedding"]` read + the existing internal L2-normalization stay. The
`OLLAMA_EMBED_MODEL_NAME != OLLAMA_MODEL_NAME` model-separation guard is retained (§8). (Construct the
client per call — cheap for an offline script; keeps the swap to one line.)

**3.3 Provenance marker (D3) — `build_kb.py` write side.** After `faiss.write_index(...)`, write a
sibling marker (OQ#5 resolved → sibling file, since `clauses_meta.jsonl` is line-delimited records with
no single-stamp slot):
```python
# writes data/kb/clauses.faiss.provider  (next to CRAG_KB_INDEX_PATH)
Path(str(index_path) + ".provider").write_text(
    json.dumps({"provider": config.EMBED_PROVIDER, "model": <active embed model>}),
    encoding="utf-8")
```
where `<active embed model>` is `HF_EMBED_MODEL` when `EMBED_PROVIDER=hf` else `OLLAMA_EMBED_MODEL_NAME`.

**3.4 Provenance mismatch WARNING (D3) — `app/graph/nodes/retrievers/kb_retriever.py::load_kb`,
runtime read side.** Right after the successful `faiss.read_index(...)` (line ~70), read the sibling
`.provider` marker (if present) and, if it disagrees with the active `EMBED_PROVIDER`/embed model, emit
a single loud `logger.warning(...)` (matching the existing unavailability-warning style at lines 57-66).
**Warning only — never a hard failure** (a missing marker on a legacy index is tolerated silently; a
mismatch warns but still serves, since the operator may be mid-rebuild). This makes EC-7 detectable
without changing retrieval behavior.

## 4. Deps
- **None added.** OQ#4 resolved → raw `httpx` (already in `pyproject.toml`). No `uv lock`/`uv sync`
  needed; the CI dep-audit is unaffected.

## 5. Test plan (TDD, `tests/unit/`) — failing-first per §7, **`httpx` MOCKED, no network**
Mock strategy: monkeypatch `app.llm.embed_client.httpx.post` to return a fake response object exposing
`.status_code`, `.json()`, and `.raise_for_status()`; monkeypatch the bare module-level
`EMBED_PROVIDER`/`HF_API_TOKEN`/… for dispatch and config-driven behavior.

- **AC-1 (`test_embed_client.py`):** `get_embed_client(t)` → `ollama.Client` when `EMBED_PROVIDER="ollama"`;
  `HFEmbedClient` when `"hf"` (with a stub `HF_API_TOKEN`).
- **AC-2:** mocked 200 body = a `EMBED_DIM`-float list → `HFEmbedClient.embeddings(model="bge-m3",
  prompt="x")` returns `{"embedding": [<EMBED_DIM floats>]}` (raw), and the POST went to a URL containing
  `HF_EMBED_MODEL` with `json={"inputs":"x"}` (assert captured args).
- **AC-3 (model override, §8):** the POST always targets `HF_EMBED_MODEL` regardless of the `model=`
  argument; a test asserts the HF path only ever forms the embedding-model URL (never a generative
  model name).
- **AC-4 (runtime failure → None):** with `EMBED_PROVIDER="hf"`, mock httpx to (a) raise
  `httpx.TimeoutException`, (b) return a persistent 503 (retry-exhausted), (c) return a wrong-shape body
  → `embed_query(...)` returns `None` and does not raise (patched into the real `_call_embed` path). A
  zero-norm vector also → `None`.
- **AC-5 (reversibility / no-op default — BOTH sites):** with `EMBED_PROVIDER="ollama"`,
  `embeddings.py::_call_embed` and `build_kb.py::_embed` both route through `get_embed_client` and get an
  `ollama.Client` (spy on `get_embed_client` / assert the ollama path, reusing each site's existing
  ollama mock).
- **AC-6 (token hygiene):** missing `HF_API_TOKEN` + `EMBED_PROVIDER="hf"` → `ValueError` whose message
  does NOT contain the token; assert no `logger` call and no exception text includes the token value.
- **AC-7 (`test_config.py`):** `EMBED_PROVIDER` default `"ollama"` and ∈ {ollama, hf}; `HF_EMBED_MODEL`
  non-empty str; `HF_EMBED_MAX_RETRIES` int; `EMBED_DIM` int (1024).
- **AC-8 (dimension parity):** a wrong-length / nested HF body → `ValueError` in the adapter → `None`
  (runtime) / raises in `build_kb`; a correct `EMBED_DIM` body passes.
- **Provenance (supports D3/EC-7):** `build_kb` writes `clauses.faiss.provider` with the active
  provider/model; `load_kb` logs a warning when the marker disagrees with the active provider and stays
  silent when it matches or is absent.
- **AC-9:** whole `pytest` green; `git diff --name-only main` = the §0 allow-list (no
  graph/edge/`ContractState`/migration/generation/frontend change; `OLLAMA_MODEL_NAME` unchanged after
  the revert; no `pyproject`/`uv.lock` change).

## 6. Measurement (AC-10, live — after backend green; deferred from the merge gate)
With `EMBED_PROVIDER=hf`, `HF_EMBED_MODEL=BAAI/bge-m3`, `HF_API_TOKEN` set: rebuild the index
(`EMBED_PROVIDER=hf python scripts/build_kb.py` → new `clauses.faiss` + `.provider`), then run
`python -X utf8 -m eval.harness.run` + `score` on the **same gold subset used for 046's AC-9**
(`specs/046-groq-llm-provider/RESULTS.md`). Report retrieval-path hit-rate, CRAG `confidence_score`
distribution, and downstream recall/precision/false-flag vs the Ollama-`bge-m3` baseline; note whether
the 0.73 cutoff still behaves for HF vectors (re-tune is a separate, measured follow-up — §3 constant).
Honest framing: candidate labels (`docs/ACCURACY.md`).

## 7. Risks / limitations
- **Third-party egress** (spec §1) — OFF by default (`EMBED_PROVIDER=ollama`); operator opt-in; clause
  text only; `HF_API_TOKEN` gitignored + never logged. Reversible.
- **HF free-tier volume caps** — a 429/again-later that retries can't clear degrades gracefully to
  `None` → CRAG circuit breaker / web fallback, never a crash. If reliability proves inadequate at
  volume (AC-10 / live use), pivot the provider (Jina/Deepinfra) as a follow-up — the seam makes that a
  localized change.
- **Provider/index mismatch (EC-7)** — the `.provider` marker + `load_kb` warning make it detectable;
  the true fix is a rebuild. Documented as operator duty in `docs/DEPLOYMENT.md`. Not silently corrected.
- **HF pre-normalized vectors** — idempotent with the existing L2-normalize (probe-confirmed); no code
  change needed.

## 8. Merge
Whole `pytest` green; diff scope = §0 allow-list; **`OLLAMA_MODEL_NAME` reverted to qwen3:8b**; no dep
change. Rebase `main`, merge `feature/050-embedding-provider`, delete branch (`git-finish`); re-apply the
local qwen3:4b override afterward. AC-10 live measurement + the `docs/DEPLOYMENT.md` rebuild note follow
the merge (as 046's AC-9 did). This is the first feature of the Render+Turso deploy chain
([[project_render_turso_deploy]]); 051 (Turso persistence) stacks next.
