# Feature 046 — Technical plan: LLM provider adapter (Groq generation, Ollama embeddings)

Branch: `feature/046-groq-llm-provider` (per constitution §11).

Derived from `spec.md`. Adds a provider seam: the **5 generative chat call sites (across 4 files)**
route through a factory that returns either today's `ollama.Client` (default) or a `GroqChatClient`
that mimics Ollama's `.chat()` shape. Embeddings stay on Ollama (§8). **No graph/edge/`ContractState`/
migration change.**

## 0. Scope of change (files touched)

Per **AC-8** the `git diff --name-only main` must show only:
```
backend/app/config.py                                  (config + load_dotenv)
backend/app/llm/chat_client.py                         (NEW — factory + GroqChatClient)
backend/app/graph/nodes/splitters/llm_refiner.py       (1-line client swap)
backend/app/graph/nodes/validators/reflectors.py       (2-line swap — _call_ollama + _call_combined)
backend/app/graph/nodes/scorers/risk_scorer.py         (1-line client swap)
backend/app/graph/nodes/drafters/redline_drafter.py    (1-line client swap)
backend/pyproject.toml                                 (add groq dep)
backend/uv.lock                                        (locked)
backend/tests/unit/test_chat_client.py                 (NEW)
backend/tests/unit/test_config.py                      (AC-7)
backend/tests/unit/test_{llm_refiner,reflectors,risk_scorer,redline_drafter}_*  (AC-5, as needed)
specs/046-groq-llm-provider/{spec,plan,tasks}.md
```
`embeddings.py` is **NOT** touched. **⚠ Revert the local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b before
committing** (breaks 4 `test_config` asserts); re-apply after merge for local runs.

## 1. Config + `.env` loading (`app/config.py`)

- **`load_dotenv()` at the very top**, before any `os.getenv` runs:
  ```python
  from dotenv import load_dotenv
  load_dotenv()  # feature 046: read backend/.env (GROQ_API_KEY etc.); real env vars still win.
  ```
  Placed immediately after `import os` (line ~11), before the constant reads. Idempotent; no-op if no
  `.env`. (`python-dotenv` is already a dependency.)
- **New constants** (near the Ollama block, env-read):
  ```python
  LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama").strip().lower()   # "ollama" | "groq"
  GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
  GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
  GROQ_REASONING_EFFORT: str = os.getenv("GROQ_REASONING_EFFORT", "low")
  GROQ_MAX_RETRIES: int = _env_int("GROQ_MAX_RETRIES", 2)
  ```
  Comment: default `ollama` ⇒ byte-for-byte today; `groq` routes generation to Groq (embeddings stay
  local, §8). Do **not** log `GROQ_API_KEY`.

## 2. Adapter (`app/llm/chat_client.py`, NEW)

```python
"""Provider seam (feature 046). get_chat_client() returns an Ollama client (default) or a
GroqChatClient that mimics ollama.Client.chat's signature + {"message":{"content":...}} return, so
generative nodes swap one line. Embeddings stay on Ollama (constitution §8). GROQ_API_KEY is never
logged."""
import ollama
import app.config as _config

LLM_PROVIDER = _config.LLM_PROVIDER            # bare names for monkeypatch (read at call time)
GROQ_API_KEY = _config.GROQ_API_KEY
GROQ_MODEL = _config.GROQ_MODEL
GROQ_REASONING_EFFORT = _config.GROQ_REASONING_EFFORT
GROQ_MAX_RETRIES = _config.GROQ_MAX_RETRIES


class GroqChatClient:
    """Mimics ollama.Client for the .chat() call the generative nodes make."""
    def __init__(self, timeout_seconds: float):
        if not GROQ_API_KEY:
            raise ValueError(
                "LLM_PROVIDER=groq but GROQ_API_KEY is empty — set it in backend/.env "
                "(see docs/DEPLOYMENT.md). (key value intentionally not shown)"
            )
        from groq import Groq  # imported lazily so the dep is only needed on the groq path
        self._client = Groq(api_key=GROQ_API_KEY, max_retries=GROQ_MAX_RETRIES,
                            timeout=float(timeout_seconds))

    def chat(self, model=None, messages=None, format=None, think=None, options=None, **_):
        opts = options or {}
        kwargs = {
            "model": GROQ_MODEL,                 # D7: ignore the passed ollama model name
            "messages": messages,
            "temperature": opts.get("temperature", 0.0),
            "reasoning_effort": GROQ_REASONING_EFFORT,   # replaces think=False intent (D4)
        }
        if format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        if "num_predict" in opts:
            kwargs["max_completion_tokens"] = opts["num_predict"]
        if opts.get("seed") is not None:
            kwargs["seed"] = opts["seed"]
        resp = self._client.chat.completions.create(**kwargs)
        return {"message": {"content": resp.choices[0].message.content}}


def get_chat_client(timeout_seconds: float):
    """Factory: ollama.Client (default) or GroqChatClient, per LLM_PROVIDER (read live)."""
    if LLM_PROVIDER == "groq":
        return GroqChatClient(timeout_seconds)
    return ollama.Client(timeout=timeout_seconds)
```

- **Key never logged (AC-6):** the missing-key error and any exception text never include the key.
- **429/backoff (D5):** handled by the Groq SDK's `max_retries` (exponential backoff) — no bespoke
  loop; a transient 429 retries rather than tripping the node failsafe.
- **Reasoning (D4):** `reasoning_effort=GROQ_REASONING_EFFORT` ("low") — measured valid JSON with
  headroom; reasoning does not leak into `content` under `response_format=json_object`.
- **`app/llm/__init__.py`** already exists (feature 035) — no new package marker.

## 3. Wire-in (5 sites, 4 files)

In each generative `_call_ollama` / `_call_combined`, replace the client construction only:
```python
# before:  client = ollama.Client(timeout=timeout_seconds)
from app.llm.chat_client import get_chat_client   # module-level import
client = get_chat_client(timeout_seconds)
```
- `llm_refiner.py` (1) · `risk_scorer.py` (1) · `redline_drafter.py` (1) · **`reflectors.py` (2 —
  `_call_ollama` AND `_call_combined`)**.
- The `client.chat(model=..., messages=..., format="json", think=False, options={...})` call and the
  `response["message"]["content"]` read are **unchanged** — the adapter matches that shape.
- `embeddings.py` keeps `ollama.Client(...).embeddings(...)` untouched (§8).

## 4. Deps
- Add `"groq>=0.11"` to `backend/pyproject.toml` `dependencies`; run `uv lock`; `uv sync`. The Groq SDK
  sets a proper User-Agent (avoids the Cloudflare 403 error-1010 that blocks raw urllib), and provides
  `response_format` + `reasoning_effort` + `max_retries`. CI dep-audit still runs on the new lock.

## 5. Test plan (TDD, `tests/unit/`)
Failing-first per §7. **Groq SDK MOCKED — no network in the suite.** Mock `groq.Groq` so
`client.chat.completions.create(...)` returns an object with `.choices[0].message.content`.

- **AC-1 (`test_chat_client.py`):** `get_chat_client(t)` → `ollama.Client` when `LLM_PROVIDER="ollama"`;
  `GroqChatClient` when `"groq"` (monkeypatch the module-level `LLM_PROVIDER` + a stub `GROQ_API_KEY`).
- **AC-2:** `GroqChatClient.chat(model="qwen3:8b", messages=M, format="json", think=False,
  options={"num_predict":384,"temperature":0.0,"seed":42})` calls the mocked SDK with
  `model=GROQ_MODEL, messages=M, response_format={"type":"json_object"}, reasoning_effort="low",
  max_completion_tokens=384, temperature=0.0, seed=42` (assert on the captured kwargs).
- **AC-3:** mocked content `'{"risk_level":"high"}'` → `.chat(...)` returns
  `{"message":{"content":'{"risk_level":"high"}'}}`.
- **AC-6:** `max_retries=GROQ_MAX_RETRIES` passed to the SDK ctor; a mocked side-effect of
  `[RateLimit, success]` (or asserting `max_retries` is set) returns success; **missing key →
  `ValueError` whose message does NOT contain the key**; assert no logger call includes the key.
- **AC-4 (§8):** a test asserts `embeddings.py` does not import `get_chat_client` and still builds
  `ollama.Client` even when `LLM_PROVIDER="groq"` (grep-style import assertion + the embed path).
- **AC-5 (all 5 sites):** for each of the 5 sites, with `LLM_PROVIDER="ollama"` the node still uses
  `ollama.Client` (patch `get_chat_client` to a spy and assert it is called with the site's
  `timeout_seconds`; and/or assert the ollama path). Explicitly include a `reflectors._call_combined`
  test with `SELF_RAG_MERGE_JUDGMENTS=True` so the merged path's swap is covered. Reuse each node's
  existing test-mock style (they already patch `ollama.Client` / the chat response).
- **AC-7 (`test_config.py`):** `LLM_PROVIDER` default `"ollama"` and ∈ {ollama, groq}; `GROQ_MODEL` /
  `GROQ_REASONING_EFFORT` non-empty str; `GROQ_MAX_RETRIES` int.
- **AC-8:** whole suite green; `git diff --name-only main` = the allow-list (no embeddings/graph
  change; `OLLAMA_MODEL_NAME` unchanged after the revert).

## 6. Measurement (AC-9, live — after backend green)
With `LLM_PROVIDER=groq`, `GROQ_MODEL=openai/gpt-oss-120b`, `bge-m3` on local Ollama, delivery OFF, run
`python -X utf8 -m eval.harness.run` + `score` on the 6-doc large subset (as in 042/045). Record recall
/ precision / false-flag / severity vs the qwen3:8b baseline (`eval/runs/BEFORE_042subset`), and
specifically whether the previously-missed **liability-cap** clauses flip fn→tp. Watch the 256/384-budget
sites for `finish_reason=length` truncation (EC-4). Honest framing: candidate labels (ACCURACY.md); the
qwen3 numbers do not carry over. Report as a RESULTS note.

## 7. Risks / limitations
- **Third-party egress** (spec §1 privacy posture) — OFF by default; operator opt-in + no-train tier +
  ToS duty; key gitignored + never logged.
- **Truncation on tiny budgets** — measured `finish=stop` at 384; a config bump fixes any site that
  truncates (no code change). EC-4.
- **New runtime dep (`groq`)** — surfaces in the dep-audit; pin a maintained version.

## 8. Merge
- Whole `pytest` green; diff scope = allow-list; **`OLLAMA_MODEL_NAME` reverted to qwen3:8b**. Rebase
  `main`, merge `feature/046-groq-llm-provider`, delete branch (`git-finish`); re-apply qwen3:4b
  locally. (AC-9 live measurement can follow the merge, like other features' harness runs.)
