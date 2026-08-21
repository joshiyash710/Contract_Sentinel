# Feature 046 — LLM provider adapter (Groq generation) — Tasks

Reference documents:
- Spec: `specs/046-groq-llm-provider/spec.md`
- Plan: `specs/046-groq-llm-provider/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** no graph/edge/state; **§3** named env config;
  **§7** TDD + never weaken; **§8** embeddings stay on Ollama/bge-m3; **§11** branch-gated)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **TDD (§7):** tests written FAILING first; **Groq SDK MOCKED — no network in the suite.**
- **Scope (AC-8):** `app/config.py`, `app/llm/chat_client.py` (NEW), the 4 generative node files
  (5 call sites — `reflectors.py` has 2), `pyproject.toml` + `uv.lock`, tests, `specs/046-**`.
  **`app/graph/nodes/retrievers/embeddings.py` is NOT touched** (§8 — bge-m3 stays on Ollama).
- **⚠ Revert local `OLLAMA_MODEL_NAME` qwen3:4b → qwen3:8b BEFORE committing** (breaks 4 config
  tests); re-apply after merge.
- **`GROQ_API_KEY` is never logged** — no log line or exception message may contain it (AC-6).
- Default `LLM_PROVIDER="ollama"` ⇒ byte-for-byte today's behavior.

---

## Task 0: Branch (done — confirm)
- [x] On `feature/046-groq-llm-provider`; spec + plan spec-reviewer-APPROVED. Commit spec/plan/tasks.

**Verify:** `git branch --show-current` → `feature/046-groq-llm-provider`.

---

## Task 1: Add the `groq` dependency
- [ ] **[MODIFY] `pyproject.toml`** — add `"groq>=0.11"` to `[project].dependencies`. Run
  `uv lock` then `uv sync --frozen --extra dev` (restores pytest). Confirm `python -c "import groq"`.

**Verify:** `python -c "import groq; print(groq.__version__)"` succeeds; `uv.lock` updated.

---

## Task 2: Config + `.env` loading (§3)  [AC-7]
- [ ] **[MODIFY] `app/config.py`** — add `from dotenv import load_dotenv` + `load_dotenv()` at the top
  (after `import os`, before any `os.getenv` read). Add the 5 constants (env-read) near the Ollama
  block: `LLM_PROVIDER` (default `"ollama"`, lowercased), `GROQ_API_KEY` (`""`), `GROQ_MODEL`
  (`"openai/gpt-oss-120b"`), `GROQ_REASONING_EFFORT` (`"low"`), `GROQ_MAX_RETRIES` (`_env_int`, 2).
  Comment: default ollama ⇒ unchanged; groq routes generation only (embeddings local, §8); never log
  the key.

**Verify:** `python -c "import app.config as c; print(c.LLM_PROVIDER, c.GROQ_MODEL)"` → `ollama openai/gpt-oss-120b`.

---

## Task 3: Config validity test (red → green)  [AC-7]
- [ ] **[MODIFY] `tests/unit/test_config.py`** (FAIL first): assert `LLM_PROVIDER` default `"ollama"`
  and ∈ {"ollama","groq"}; `GROQ_MODEL`/`GROQ_REASONING_EFFORT` non-empty `str`; `GROQ_MAX_RETRIES`
  `int`. Task 2 makes it green.

**Verify:** `python -m pytest tests/unit/test_config.py -q -k "llm_provider or groq"` → PASS.

---

## Task 4: Adapter — tests (red) → implementation (green)  [AC-1..AC-4, AC-6]
- [ ] **[NEW] `tests/unit/test_chat_client.py`** (FAIL first — module absent), Groq SDK MOCKED
  (patch `groq.Groq` so `.chat.completions.create(**kw)` records kwargs and returns an object with
  `.choices[0].message.content`):
  - **AC-1:** `get_chat_client(t)` → `ollama.Client` when `LLM_PROVIDER="ollama"`; `GroqChatClient`
    when `"groq"` (monkeypatch `chat_client.LLM_PROVIDER` + a stub `chat_client.GROQ_API_KEY`).
  - **AC-2:** `.chat(model="qwen3:8b", messages=M, format="json", think=False,
    options={"num_predict":384,"temperature":0.0,"seed":42})` → SDK called with `model=GROQ_MODEL`,
    `messages=M`, `response_format={"type":"json_object"}`, `reasoning_effort="low"`,
    `max_completion_tokens=384`, `temperature=0.0`, `seed=42`.
  - **AC-3:** mocked content `'{"risk_level":"high"}'` → returns
    `{"message":{"content":'{"risk_level":"high"}'}}`.
  - **AC-6:** SDK ctor gets `max_retries=GROQ_MAX_RETRIES`; **missing `GROQ_API_KEY` +
    `LLM_PROVIDER="groq"` → `ValueError` whose message does NOT contain the (stub) key**; assert no
    logger output contains the key.
  - **EC-2:** `options` without `seed`/`num_predict` → those kwargs omitted (no crash).
  - **AC-4 (§8 embeddings guard):** assert `app/graph/nodes/retrievers/embeddings.py` does NOT import
    `get_chat_client` (e.g. read its source / import table) and that the embedding path builds
    `ollama.Client` even when `LLM_PROVIDER="groq"` — embeddings never route to Groq.
- [ ] **[NEW] `app/llm/chat_client.py`** — implement per plan §2: bare module-level
  `LLM_PROVIDER`/`GROQ_*` (read at call time, monkeypatchable); `GroqChatClient` (lazy
  `from groq import Groq`, missing-key `ValueError` without the key, translate params, return
  `{"message":{"content":…}}`); `get_chat_client(timeout)` factory.

**Verify:** `python -m pytest tests/unit/test_chat_client.py -q` → PASS.

---

## Task 5: Wire-in the 5 call sites (green)  [AC-5]
- [ ] **[MODIFY]** in each, replace `client = ollama.Client(timeout=timeout_seconds)` with
  `client = get_chat_client(timeout_seconds)` (module-level `from app.llm.chat_client import
  get_chat_client`), leaving the `.chat(...)` call + `response["message"]["content"]` parse unchanged:
  - `app/graph/nodes/splitters/llm_refiner.py` (`_call_ollama`)
  - `app/graph/nodes/validators/reflectors.py` (**`_call_ollama` AND `_call_combined`**)
  - `app/graph/nodes/scorers/risk_scorer.py` (`_call_ollama`)
  - `app/graph/nodes/drafters/redline_drafter.py` (`_call_ollama`)
- [ ] **[MODIFY] the affected node tests** for AC-5 — REQUIRED, not optional. The existing node tests
  patch the client at `<node>.ollama.Client` (e.g.
  `patch("app.graph.nodes.validators.reflectors.ollama.Client", …)`). After the wire-in the client is
  built **inside `get_chat_client` (in `app/llm/chat_client.py`)**, so those module-local patch targets
  **no longer intercept** it. **Re-point each such patch to `app.llm.chat_client.ollama.Client`** (the
  default-ollama path constructs `ollama.Client` there) — the existing mock-client-returns-verdict
  machinery then works unchanged with a one-string patch-target change per site. Do this in the real
  files: **`test_llm_refiner.py`, `test_self_rag_reflectors.py`, `test_risk_scorer.py`,
  `test_redline_drafter.py`** (confirm each file's actual patch strings; also check the sibling
  `test_risk_score_agent.py` / `test_redline_agent.py` if they patch the client). Add/confirm a
  **`reflectors._call_combined`** case with `SELF_RAG_MERGE_JUDGMENTS=True` so the merged path's swap is
  covered. If a node's `import ollama` becomes unused after the swap, remove it (keep the diff clean).
- [ ] **[CONFIRM] `embeddings.py` untouched** — the AC-4 guard test (asserting `embeddings.py` does NOT
  import `get_chat_client` and still builds `ollama.Client` even when `LLM_PROVIDER="groq"`) lives in
  **Task 4's `test_chat_client.py`** (pinned there, not split across tasks).

**Verify:** `python -m pytest tests/unit/test_llm_refiner.py tests/unit/test_self_rag_reflectors.py tests/unit/test_risk_scorer.py tests/unit/test_redline_drafter.py tests/unit/test_risk_score_agent.py tests/unit/test_redline_agent.py -q` → PASS (adjust to the filenames that actually exist).

---

## Task 6: Full suite + scope gate  [AC-8]
- [ ] Revert local `OLLAMA_MODEL_NAME` → `qwen3:8b`. `python -m pytest -q` → GREEN (pin any surprised
  test with justification, never weaken).
- [ ] `git diff --name-only main` = the allow-list (config, chat_client, 4 node files, pyproject,
  uv.lock, tests, specs) — **no `embeddings.py`, no graph/edge/state/migration change**, and
  `OLLAMA_MODEL_NAME == "qwen3:8b"` in the diff.

**Verify:** suite green; diff scope confirmed.

---

## Task 7: Merge  (+ Task 8 live measurement can follow)
- [ ] Whole `pytest` green; diff scope confirmed; qwen3:8b reverted. Rebase `main`, merge
  `feature/046-groq-llm-provider`, delete branch (`git-finish`); re-apply qwen3:4b locally.

## Task 8: AC-9 live measurement (after merge, needs Groq key + local Ollama for bge-m3)
- [ ] Set `LLM_PROVIDER=groq`, `GROQ_MODEL=openai/gpt-oss-120b` (in `backend/.env`), Ollama up with
  `bge-m3`, delivery OFF. Run `python -X utf8 -m eval.harness.run` + `score` on the 6-doc large subset;
  compare recall/precision/false-flag/severity vs `eval/runs/BEFORE_042subset`; confirm the
  liability-cap fn→tp recovery; watch the 256/384-budget sites for `finish_reason=length`. Record a
  RESULTS note (honest candidate-label framing).

---

*Per §1/§11, implementation happens only on `feature/046-groq-llm-provider`. Provider seam only — no
`ContractState`, no graph/edge, no migration, embeddings stay on Ollama (§8). Default `LLM_PROVIDER=
ollama` ⇒ byte-for-byte today; `groq` is an opt-in, key-gitignored, key-never-logged, reversible path
(see spec §1 privacy posture).*
