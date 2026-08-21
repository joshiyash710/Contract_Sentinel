# Feature 046 — LLM provider adapter (Groq generation, Ollama embeddings)

Branch: `feature/046-groq-llm-provider` (per constitution §11).

## 1. Problem statement

All 5 generative LLM calls run on the local `qwen3:8b` via `ollama.Client(...).chat(...)`. The accuracy
diagnostic ([[docs/ACCURACY.md]]) showed the genuine recall misses are **model-judgment** failures
(liability-limitation clauses the small model finds relevant then drops at the support check). The
single highest-value lever is a **stronger generative model**; it is also the **deployment prerequisite**
(there is no free always-on GPU — `docs/DEPLOYMENT.md` routes generation to Groq's free API while
`bge-m3` embeddings stay local/free).

This feature adds a **provider seam**: generation goes to **Groq** (default model
`openai/gpt-oss-120b`) when configured, while embeddings remain on **Ollama `bge-m3`**. It is
**measured, not assumed** — an offline live probe already confirmed `gpt-oss-120b` returns valid,
parseable JSON within the pipeline's tight token budgets and **correctly scores a liability-cap clause
`high`** (the exact clause type `qwen3:8b` was missing). §7 re-runs the eval harness on the new model.

### Position relative to the constitution
No graph/edge change, no `ContractState` change, no migration. This swaps *which client* the existing
generative nodes call, behind a **named §3 config flag** (`LLM_PROVIDER`, default `ollama` ⇒
byte-for-byte today's behavior). §7 the adapter is TDD-unit-tested with the Groq SDK mocked (no
network in the suite). §8 the embedding model separation (constitution §8) is preserved — **embeddings
NEVER go to Groq**; only the **5 generative chat call sites (across 4 files — `reflectors.py` has 2:
`_call_ollama` and the Lever-C `_call_combined`)** switch. Developed on `feature/046-groq-llm-provider`
(§1/§11).

### Privacy / data-egress posture (explicit — constitution §2 acknowledgment)
**This feature is the first that can send confidential contract text off the machine.** With
`LLM_PROVIDER=groq`, each generative node transmits its prompt — which contains **clause text,
retrieved evidence snippets, and LLM-derived rationale** — to **Groq (a third party)** over TLS. That
is a material departure from the project's local-first / encryption-at-rest posture (constitution §2
amendments 019 per-user isolation, 032/036 encryption at rest). This is called out explicitly, not
slipped in.

**Resolution — an accepted, documented, OPT-IN interim posture** (mirroring how 031's plaintext-token
interim posture was explicitly noted), **not** a silent change:
- **OFF by default.** `LLM_PROVIDER=ollama` is the default ⇒ **local runs remain fully private**;
  egress happens only when an operator deliberately sets `LLM_PROVIDER=groq` (a deployment choice the
  user has explicitly accepted — cost/privacy trade for the free deploy, see `docs/DEPLOYMENT.md`).
- **Scope of what is sent:** only the clause/evidence/rationale already assembled for the LLM prompt
  (and already prompt-guard-fenced, feature 035). **No** auth tokens, OAuth credentials, encryption
  keys, user PII, or file bytes beyond the clause text are sent. Embeddings never leave (§8).
- **Operator duty:** the deploying operator must choose a Groq tier/policy that does **not** train on
  submitted data, and must surface this in the product's privacy/ToS (paired with the "not legal
  advice" disclaimer). Documented in `docs/DEPLOYMENT.md`.
- **Secret hygiene:** `GROQ_API_KEY` is read from env/`.env` (gitignored) and **must never be logged**
  (AC-6), mirroring the §032 encryption-key handling discipline.
- **Reversibility:** flipping `LLM_PROVIDER` back to `ollama` restores the fully-local posture with no
  data egress. This is an interim opt-in relaxation, not a permanent constitutional change; a formal
  §2 amendment can be recorded if/when Groq becomes the shipped default.

## 2. Inputs and outputs

### 2.1 New config (§3, env-overridable)
- `LLM_PROVIDER: str` — `"ollama"` | `"groq"`. **Default `"ollama"`** (byte-for-byte today). Read via
  env so the deploy sets `LLM_PROVIDER=groq` without a code change.
- `GROQ_API_KEY: str` — from env (`.env` / real env var); default `""`.
- `GROQ_MODEL: str` — default `"openai/gpt-oss-120b"` (the strongest chat model confirmed available on
  the user's key; `qwen/qwen3.6-27b` / `openai/gpt-oss-20b` are drop-in alternatives via env).
- `GROQ_REASONING_EFFORT: str` — default `"low"` (measured: valid JSON, lower tokens/latency, correct
  answers; gpt-oss is a reasoning model — this replaces the Ollama `think=False` intent).
- `GROQ_MAX_RETRIES: int` — default `2` (the Groq SDK's built-in exponential backoff handles 429 /
  transient errors — no failsafe on a rate-limit).
- `GROQ_TIMEOUT_SECONDS` is **not** new — the adapter reuses each call site's existing
  `timeout_seconds` (the ThreadPoolExecutor abort bound is unchanged).

### 2.2 `.env` loading (NEW)
`load_dotenv()` is currently **never called**, so `.env` is not read. Add a single early
`load_dotenv()` at the **top of `app/config.py`** (before any `os.getenv`) so `GROQ_API_KEY` etc. from
`backend/.env` are available. `python-dotenv` is already a dependency. Idempotent; no-op if `.env`
absent (real env vars still win via `os.getenv`).

### 2.3 The adapter (NEW `app/llm/chat_client.py`)
A factory `get_chat_client(timeout_seconds)` returning a client whose `.chat(...)` **mimics
`ollama.Client.chat`'s signature and return shape** so the call sites change by one line each:
- `LLM_PROVIDER == "ollama"` → returns `ollama.Client(timeout=timeout_seconds)` (unchanged path).
- `LLM_PROVIDER == "groq"` → returns a `GroqChatClient` whose
  `.chat(model, messages, format=None, think=None, options=None, **_) -> dict` translates to Groq and
  returns `{"message": {"content": <str>}}` (the exact shape callers already read as
  `response["message"]["content"]`).

**Parameter translation (Ollama → Groq/OpenAI-compatible):**
| Ollama chat arg | Groq `chat.completions.create` arg |
|---|---|
| `model` (the Ollama name) | **ignored**; adapter uses `GROQ_MODEL` |
| `messages` | `messages` (unchanged; system/user from prompt_guard preserved) |
| `format="json"` | `response_format={"type":"json_object"}` |
| `think=False` | `reasoning_effort=GROQ_REASONING_EFFORT` (`"low"`) |
| `options["num_predict"]` | `max_completion_tokens` (same integer budget) |
| `options["temperature"]` | `temperature` |
| `options["seed"]` (if set) | `seed` |

The `Groq(api_key=…, max_retries=GROQ_MAX_RETRIES, timeout=timeout_seconds)` client sets a proper
User-Agent (raw `urllib`/`requests` is blocked by Groq's edge with **Cloudflare 403 error 1010** — the
SDK avoids this).

### 2.4 Wire-in (4 generative node files)
In `llm_refiner.py`, `reflectors.py` (both call sites), `risk_scorer.py`, `redline_drafter.py`,
replace `client = ollama.Client(timeout=timeout_seconds)` with
`client = get_chat_client(timeout_seconds)`. **Nothing else changes** — the `client.chat(...)` call,
its args, and the `response["message"]["content"]` read are identical. `embeddings.py` is **NOT
touched** (bge-m3 stays on Ollama — §8).

### 2.5 Output
No new state field, no report/schema change. With `LLM_PROVIDER=groq`, the 4 generative nodes'
judgments come from Groq; embeddings, graph, edges, and downstream contracts are unchanged.

## 3. Resolved decisions (inline)
- **D1 — Default `LLM_PROVIDER=ollama`.** Zero behavior change until explicitly switched; the deploy
  sets `groq` via env. Reversible.
- **D2 — Mimic Ollama's `.chat()` dict shape.** Smallest blast radius (one line per call site); the
  4 nodes' parsing/prompt/timeouts are untouched.
- **D3 — Embeddings stay on Ollama (§8).** Only generation moves; `bge-m3` never goes to Groq. The
  model-separation invariant is preserved and unit-guarded.
- **D4 — `gpt-oss-120b` + `reasoning_effort="low"` + `response_format=json_object`.** Measured: valid
  JSON at 384-token budget (`finish=stop`), correct `high` on a liability cap, ~1s. Config-swappable.
- **D5 — 429/backoff via the Groq SDK** (`max_retries` + built-in exponential backoff) so a rate-limit
  retries instead of tripping the failsafe. No bespoke retry loop.
- **D6 — Use the official `groq` SDK** (new runtime dep). It handles auth, the required User-Agent
  (Cloudflare gotcha), retries, and `response_format` — more robust than raw HTTP. `python-dotenv`
  (already a dep) loads `.env`.
- **D7 — `GROQ_MODEL` overrides the passed model.** Call sites still pass `OLLAMA_MODEL_NAME`; the
  Groq client ignores it and uses `GROQ_MODEL`, so no call-site signature change.

## 4. Acceptance criteria

### Backend (pytest — all offline, Groq SDK MOCKED, no network)
- **AC-1 (factory dispatch):** `get_chat_client(t)` returns an `ollama.Client` when
  `LLM_PROVIDER="ollama"` and a `GroqChatClient` when `LLM_PROVIDER="groq"`.
- **AC-2 (param translation):** `GroqChatClient.chat(model="qwen3:8b", messages=M, format="json",
  think=False, options={"num_predict":384,"temperature":0.0,"seed":42})` calls the (mocked) Groq SDK
  with `model=GROQ_MODEL`, `messages=M`, `response_format={"type":"json_object"}`,
  `reasoning_effort="low"`, `max_completion_tokens=384`, `temperature=0.0`, `seed=42`.
- **AC-3 (return shape):** given a mocked Groq response with content `'{"risk_level":"high"}'`,
  `.chat(...)` returns `{"message": {"content": '{"risk_level":"high"}'}}` (so existing
  `response["message"]["content"]` + `json.loads` parsing works unchanged).
- **AC-4 (embeddings untouched, §8):** `embeddings.py` still constructs `ollama.Client` directly and
  never imports `get_chat_client`; a test asserts the embedding path does not route to Groq even when
  `LLM_PROVIDER="groq"`.
- **AC-5 (reversibility / no-op default — ALL 5 sites):** with `LLM_PROVIDER="ollama"` (default),
  **each of the 5 generative chat call sites** — `llm_refiner`, `reflectors._call_ollama`,
  **`reflectors._call_combined`** (the Lever-C merged-judgment path), `risk_scorer`,
  `redline_drafter` — routes through `get_chat_client` and constructs an `ollama.Client` exactly as
  today (byte-for-byte). A test asserts the merged-judgment path (`SELF_RAG_MERGE_JUDGMENTS=True`) is
  swapped too, so it is not silently left on a direct `ollama.Client`.
- **AC-6 (429 backoff + key hygiene):** the `GroqChatClient` builds the SDK client with
  `max_retries=GROQ_MAX_RETRIES`; a mocked 429-then-success returns the success (no exception, no
  failsafe). A missing `GROQ_API_KEY` with `LLM_PROVIDER="groq"` raises a clear config error at client
  construction (not a silent failsafe). The **`GROQ_API_KEY` is never logged** (no log/exception
  message includes it) — asserted, mirroring the §032 encryption-key discipline.
- **AC-7 (config validity):** `LLM_PROVIDER` ∈ {ollama, groq}; `GROQ_MODEL`/`GROQ_REASONING_EFFORT`
  are non-empty str; `GROQ_MAX_RETRIES` is int; `test_config` asserts these and that `LLM_PROVIDER`
  default is `"ollama"`.
- **AC-8 (no architecture change):** `git diff` touches only `app/config.py`, `app/llm/chat_client.py`
  (NEW, + `app/llm/__init__.py` if needed), the **4 generative node files** (containing the 5 swapped
  call sites — both `reflectors.py` sites included), `pyproject.toml` + `uv.lock` (add `groq`), and the
  tests (+ `specs/046-**`). **No** graph/edge/`ContractState`/migration/embeddings/frontend change.
  Whole `pytest` green.

### Live measurement (harness — AC-9)
- **AC-9:** with `LLM_PROVIDER=groq`, `GROQ_MODEL=openai/gpt-oss-120b`, and `bge-m3` on local Ollama,
  re-run the 041/026 harness (`run` + `score`) on the 6-doc large subset. Report recall / precision /
  false-flag / severity vs the qwen3:8b baseline, and specifically whether the previously-missed
  liability-cap clauses are now caught (fn→tp). Honest framing: candidate labels (per ACCURACY.md);
  the qwen3 numbers do not carry over. Needs the live Groq key + local Ollama for embeddings.

## 5. Edge cases
- **EC-1 — `format` not `"json"`** (a future non-JSON call): omit `response_format` (plain text). All
  current 5 calls pass `format="json"`, so this is defensive.
- **EC-2 — `options` missing keys:** default sensibly (no `seed` → omit; no `num_predict` → SDK
  default). Mirror today's Ollama behavior.
- **EC-3 — `GROQ_API_KEY` empty while `LLM_PROVIDER=groq`:** raise a clear, actionable error (not a
  silent degrade), so misconfiguration is obvious at startup/first call.
- **EC-4 — Groq truncates (`finish_reason="length"`):** the returned content may be invalid JSON → the
  node's existing `_parse_*` returns `None` → the existing failsafe path (unchanged). Each site's
  existing `num_predict` flows through unchanged as `max_completion_tokens` — the budgets differ per
  site (`reflectors` single 256, `risk_scorer`/`reflectors._call_combined` 384, clause-splitter
  grouping 1024, `redline` 1536, clause-splitter emit-text 4096). The live probe validated `finish=stop`
  at **384** with `reasoning_effort="low"`; the **256/384 judgment sites are the ones to watch for
  truncation in AC-9** (redline/refiner have ample headroom). If a small-budget site truncates, the
  fix is a config bump, not code.
- **EC-5 — Reasoning leakage:** measured that `response_format=json_object` returns clean JSON in
  `content` (reasoning not leaked); if a model ever returned a `reasoning`-prefixed content, the JSON
  parse would fail → failsafe (safe).
- **EC-6 — `LLM_PROVIDER` unknown value:** treated as a config error (AC-7 validation).

## 6. Out of scope
- Changing embeddings/CRAG (bge-m3 stays local, §8/D3).
- Prompt re-tuning beyond what the translation needs — the measured JSON behavior is already valid;
  any prompt refinement is a separate, measured follow-up.
- Streaming responses; multi-provider beyond ollama/groq; per-node model selection.
- The full corpus re-eval / accuracy sign-off (AC-9 is the 6-doc subset; a broader run is later).

## 7. Evaluation (metrics to log)
Unit tests (AC-1..AC-8) are the merge gate. AC-9 (live 6-doc harness on gpt-oss-120b) is the accuracy
measurement — reported honestly against the candidate-labeled corpus, focused on the liability-cap
fn→tp recovery and any precision change.

## 8. Notes for plan.md / tasks.md (pointers)
- **Config:** add `LLM_PROVIDER`/`GROQ_API_KEY`/`GROQ_MODEL`/`GROQ_REASONING_EFFORT`/`GROQ_MAX_RETRIES`
  (env-read, near the Ollama constants) + `load_dotenv()` at the very top of `config.py`.
- **Adapter:** `app/llm/chat_client.py` — `get_chat_client(timeout)` + `GroqChatClient`; translate per
  §2.3; build `Groq(api_key, max_retries, timeout)`; return `{"message":{"content":…}}`. Read config by
  bare module name for monkeypatch.
- **Wire-in:** one-line client swap in the 4 generative files; `embeddings.py` untouched.
- **Deps:** add `groq>=0.11` to `pyproject.toml`; `uv lock`; the CI dep-audit still runs.
- **Tests:** `tests/unit/test_chat_client.py` (AC-1..AC-6, Groq SDK mocked); extend the 4 node tests
  for the client-swap (AC-5) + `test_config` (AC-7). **⚠ revert local `OLLAMA_MODEL_NAME` qwen3:4b→
  qwen3:8b before committing.** TDD failing-first.
