"""
Shared configurable constants for ContractSentinel pipeline nodes.

All threshold values referenced by node logic must be defined here as named
constants — never hardcoded inline in any node — per
specs/000-constitution.md §3 (Configurable Thresholds Rule).

Future nodes (CRAG, Self-RAG, etc.) will add their own constants here.
"""

import os
from typing import Optional

from app.graph.state import RiskLevel

# ── IngestAgent thresholds ─────────────────────────────────────────────────────
# Source: specs/003-ingest-agent/spec.md §6
MIN_TEXT_LENGTH_THRESHOLD: int = 50  # chars; below → force OCR
MIN_CHAR_DENSITY_THRESHOLD: int = 100  # chars/page; below → force OCR
OCR_LOW_CONFIDENCE_THRESHOLD: float = (
    0.6  # normalised 0–1; below → flaggable downstream
)
INGEST_TIMEOUT_SECONDS: int = 60  # wall-clock seconds for parse_pdf / parse_docx

# ── ClauseSplitterAgent thresholds ─────────────────────────────────────────────
# Source: specs/004-clause-splitter-agent/spec.md §6

OLLAMA_MODEL_NAME: str = "qwen3:8b"
# The Ollama model identifier for LLM calls in the pipeline.
# Qwen3 8B runs locally via Ollama — no cloud API cost.
# PERF TUNE (constitution §3): switched from qwen3:14b (9.3GB) to qwen3:8b (5.2GB)
# because 14b did not fit the target 6GB-VRAM GPU (RTX 4050) and spilled ~35% to CPU,
# making each generation slow. 8b is much closer to VRAM-resident (~30% CPU spill) and
# runs materially faster per call, at a modest reasoning-quality trade-off.
# Used by ClauseSplitterAgent for semantic refinement and clause_type inference.
# Future nodes (CRAG, Self-RAG, etc.) may also use this constant.

OLLAMA_TEMPERATURE: float = 0.0
# Source: specs/028-determinism-variance/spec.md §2.1, plan §1 (D1).
# Sampling temperature for ALL generative Ollama chat() calls (the 4 nodes: clause-splitter
# refine, Self-RAG reflectors, risk scorer, redline drafter). 0.0 = greedy decode → repeated runs
# on the same input converge on the same output, which (a) makes the same contract yield the same
# report — a trust property for a legal tool — and (b) removes the run-to-run noise that made the
# 026/027 tuning loop hard to read. Standard choice for the structured-JSON (format="json") calls
# these already are. Raise to 0.8 to restore pre-028 default-sampling behavior (reversible). Does
# NOT eliminate GPU-float / web-fallback residual non-determinism — 028 Part B measures that.

OLLAMA_SEED: Optional[int] = 42
# Source: specs/028-determinism-variance/spec.md §2.1, plan §1 (D7).
# Fixed RNG seed passed to every generative chat() call, for reproducibility of any residual
# sampling (belt-and-braces at temperature 0). None ⇒ the "seed" key is OMITTED (Ollama picks a
# random seed) — the escape hatch the 028 variance driver uses (with a raised temperature) to probe
# true model wobble.

CLAUSE_SPLITTER_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for the LLM call in ClauseSplitterAgent.
# Conservative starting value — Qwen3 14B is fast on GPU but needs headroom
# for long contracts and CPU-only hardware. On timeout, fall back to
# regex-only output. Benchmark on first real integration test and tune down.

MIN_CLAUSE_LENGTH: int = 100
# Minimum character count for extracted_text to be worth splitting.
# Documents shorter than this are treated as a single clause.

MAX_CLAUSES_LIMIT: int = 500
# Maximum number of clauses the node will produce.
# Documents exceeding this are truncated with a logged warning.
# Safety valve against pathological regex matches on unusual formatting.

CLAUSE_SPLITTER_LLM_MAX_CLAUSES: int = 40
# §3 latency lever A: above this regex-clause count, ClauseSplitter skips the LLM refinement
# (refine_with_llm) and uses the regex splitter output directly. The real corpus clusters into
# ~8-clause (normal) and ~185-clause (large) documents; 40 keeps full LLM clause typing/boundary
# quality for normal contracts while gating only the large-doc outliers where the refine call is
# slowest. Tunable against real node_timings.

# ── CRAG thresholds ───────────────────────────────────────────────────────────
# Source: specs/005-crag-retrieval/spec.md §6
CRAG_CONFIDENCE_THRESHOLD: float = (
    0.73  # retrieval confidence split per constitution §2
)

OLLAMA_EMBED_MODEL_NAME: str = "bge-m3"
# The Ollama EMBEDDING model — distinct from OLLAMA_MODEL_NAME (generative Qwen3)
# per constitution §8 (model-separation rule). MUST NEVER be set equal to
# OLLAMA_MODEL_NAME or used for generation. Serves CRAG (and future Self-RAG)
# clause/query embedding only.

CRAG_KB_INDEX_PATH: str = "data/kb/clauses.faiss"
# Filesystem path to the prebuilt FAISS index for the local clause KB.
# Relative to the backend/ directory (the pipeline's working directory).

CRAG_KB_METADATA_PATH: str = "data/kb/clauses_meta.jsonl"
# Sidecar mapping each FAISS vector row -> {snippet_text, source_reference}.
# Row order is 1:1 with vector IDs in the index. Same backend/-relative anchor.

CRAG_TOP_K: int = 5
# Number of nearest neighbors to retrieve from the local FAISS KB per clause.

CRAG_WEB_MAX_RESULTS: int = 5
# Max results to request from the web-search fallback per clause.

CRAG_MAX_EVIDENCE_SNIPPETS: int = 5
# Hard cap on evidence_snippets stored per clause, regardless of path.

CRAG_QUERY_MAX_CHARS: int = 2000
# Clause text is truncated to this length before embedding / web querying,
# to bound embedding input and web query size (spec §4.11).

CRAG_EMBED_TIMEOUT_SECONDS: int = 30
# Wall-clock timeout for a single embedding call via Ollama. On timeout the
# clause is treated as un-scorable and falls back to the web path (spec §4.4).

CRAG_WEB_TIMEOUT_SECONDS: int = 20
# Wall-clock timeout for a single web-search call. On timeout the clause's
# evidence is treated as empty (spec §4.8).

CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE embedding failures after which the node declares the
# embedding backend down for the rest of the run and routes all remaining
# clauses straight to web (skipping the per-clause embed timeout). Resets on
# any successful embedding. Routing-semantics guarantee (spec §4.13, AC-16).

# ── Self-RAG validation thresholds ─────────────────────────────────────────────
# Source: specs/006-self-rag-validation/spec.md §6

SELF_RAG_MAX_ATTEMPTS: int = 1
# Maximum number of ISSUP ("worth flagging") judgment attempts per clause. Constitution §2 caps
# this at 3 ("retry on ISSUP fail, max 3 attempts"); §3 latency lever B tunes the DEFAULT down to
# 1 (one attempt, no retries) — retries re-ask the identical prompt on a False verdict and, with a
# near-deterministic local model (think=False), rarely change the answer, so they mostly add
# latency. Still an upper bound: retry_count = attempts_taken - 1 (0 at this default). Raise toward
# 3 to restore retries. Renames the old SELF_RAG_MAX_RETRIES placeholder (spec §8b Q2).

SELF_RAG_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for a single Self-RAG LLM call (Relevance / ISREL / one ISSUP
# attempt) via Ollama. Mirrors CLAUSE_SPLITTER_TIMEOUT_SECONDS; headroom for local
# Qwen3 per constitution §9. On timeout the clause takes the fail-open default
# outcome (spec §4.4).

SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE LLM failures after which the node declares the generative
# backend down for the rest of the run and applies the fail-open default outcome to
# all remaining clauses (skipping per-clause timeouts). Resets on any success.
# Opening emits the error_count health signal once (spec §4.8, §8a R5, AC-15/20).
# Mirrors CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD.

SELF_RAG_PROMPT_MAX_CHARS: int = 6000
# Clause text + concatenated evidence snippets are truncated to this length before
# each LLM call, to bound prompt size (spec §4.9).

SELF_RAG_HIGH_RISK_CLAUSE_TYPES: frozenset = frozenset(
    {
        "liability",
        "termination",
        "intellectual_property",
        "dispute_resolution",
    }
)
# ClauseType.value strings for which an EMPTY-EVIDENCE clause is rescued via an
# evidence-free clause-text judgment instead of a zero-LLM discard (spec §4.3 /
# §7.5 / §8a R4). Deliberately narrow: the categories where a silent miss is
# costliest. Types NOT listed (and clause_type=None) fall through to discard.
# Widen only if the empty-evidence discard metric (spec §9.6) shows real misses.
# SUPERSEDED inside the Self-RAG node by SELF_RAG_RECALL_FLOOR_TYPES (spec 027, a
# superset of this set); kept here for back-compat / its own config test.

SELF_RAG_RECALL_FLOOR_TYPES: frozenset = frozenset(
    {
        "liability",
        "termination",
        "intellectual_property",
        "confidentiality",
    }
)
# ClauseType.value strings that get the Self-RAG "recall floor" (spec 027): once a
# clause of one of these types passes the light relevance gate, it is VALIDATED
# (surfaced as a finding for human review) even if ISSUP/ISREL would discard it, or
# if it had no evidence. Rationale: for a legal tool a missed risk (false negative)
# is far costlier than a false flag, and 026 measured 0% false-flags (headroom to
# spend). SUPERSEDES SELF_RAG_HIGH_RISK_CLAUSE_TYPES inside the node; the old constant
# is kept for back-compat/config tests but is no longer read by the node. Empty set ⇒
# byte-for-byte today's Self-RAG behavior (reversible, D6).
#
# NARROWED after the AC-7 harness A/B (spec 027 D2/D3, harness-tuned): started as
# high-risk ∪ {confidentiality}; DROPPED `dispute_resolution` because it rescued zero
# measured misses (the genuine arbitration clause is already caught by the normal gate)
# yet caused the only avoidable false flag — the pipeline mis-types "Governing Law" as
# `dispute_resolution`, which the floor then flagged. Dropping it removed that false
# flag at no recall cost (recall stayed 100%). NOTE: this means an EMPTY-EVIDENCE
# dispute_resolution clause no longer takes the Branch-A rescue (it now hits the
# Branch-B zero-LLM discard) — an accepted trade for the precision gain; the real fix
# for the mis-typing is better clause typing (spec §6, out of scope). The remaining
# false flag (a standard confidentiality clause) is the accepted recall/precision cost
# of keeping `confidentiality`, which rescues a real 026 miss.

# ── RiskScore thresholds ───────────────────────────────────────────────────────
# Source: specs/007-risk-score/spec.md §6

RISK_SCORE_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for a single RiskScore LLM call (one severity judgment) via
# Ollama. Mirrors SELF_RAG_TIMEOUT_SECONDS; headroom for local Qwen3 per
# constitution §9. On timeout the finding takes the fail-safe default (spec §4.4).

RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE LLM failures after which the node declares the generative
# backend down for the rest of the run and applies the fail-safe default level to
# all remaining validated findings (skipping per-finding timeouts). Resets on any
# success. Opening emits the error_count health signal once (spec §4.5, AC-14/15).
# Mirrors SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD.

RISK_SCORE_PROMPT_MAX_CHARS: int = 6000
# Clause text + concatenated evidence snippets are truncated to this length before
# the scoring LLM call, to bound prompt size (spec §4.8). Mirrors
# SELF_RAG_PROMPT_MAX_CHARS.

RISK_RATIONALE_MAX_CHARS: int = 1000
# Generated risk_rationale is truncated to this length before being written to
# ContractState, to bound persisted state size (spec §4.9). Unlike Self-RAG's
# ephemeral candidate-finding text, risk_rationale IS persisted — 001 reserves it.

RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE: RiskLevel = RiskLevel.HIGH
# Fail-safe severity applied when a finding cannot be scored (LLM failure, timeout,
# unparseable output, empty text, or circuit open) — spec §4.4 / §7.2 / §8a R1.
# HIGH biases toward surfacing at maximum severity for human review, consistent with
# Self-RAG's fail-open to VALIDATED. Configurable because it directly shifts
# downstream Redline load; tune against real sample contracts.

# ── Redline thresholds ─────────────────────────────────────────────────────────
# Source: specs/008-route-on-risk-redline/spec.md §6

REDLINE_RISK_THRESHOLD: frozenset = frozenset(
    {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH}
)
# The set of risk levels that route a VALIDATED finding to RedlineAgent (vs
# SkipRedline). Read by BOTH route_on_risk (the edge) and RedlineAgent (the node)
# via one shared predicate so eligibility has a single source of truth (spec §7.2).
# RESOLVED to Option A — all three levels (spec §8a R1): every validated finding is
# redlined; SkipRedline fires only for documents with zero validated findings. Kept
# permissive so the spec §9 / RiskScore §9.6 redline-routing metrics can justify a
# later tightening to {MEDIUM, HIGH}. Membership is robust to a str value too because
# RiskLevel is a str-Enum (RiskLevel.LOW == "low", hash-equal). Tune against real
# sample contracts.

REDLINE_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for a single Redline LLM call (one clause rewrite) via Ollama.
# Mirrors RISK_SCORE_TIMEOUT_SECONDS; headroom for local Qwen3 per constitution §9.
# On timeout the clause takes the fail-safe: the node emits suggested_rewrite: None.

REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE LLM failures after which the node declares the generative
# backend down for the rest of the run and emits suggested_rewrite: None for all
# remaining eligible clauses (skipping per-clause timeouts). Resets on any success.
# Opening emits the error_count health signal once (spec §7.6, AC-20/23). Mirrors
# RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD.

REDLINE_PROMPT_MAX_CHARS: int = 6000
# Clause text + risk_rationale + concatenated evidence snippets are truncated to this
# combined length before the drafting LLM call, to bound prompt size (spec §4.8).
# Mirrors RISK_SCORE_PROMPT_MAX_CHARS.

REDLINE_PROMPT_RATIONALE_RESERVE_CHARS: int = 1000
# Portion of REDLINE_PROMPT_MAX_CHARS reserved for risk_rationale BEFORE the clause
# text is truncated, so a clause longer than the prompt budget cannot starve the
# rationale (the model's remediation target — it says WHY to rewrite) to a zero
# budget. Matches RISK_RATIONALE_MAX_CHARS (the max a Node-5 rationale can be), so a
# present rationale is never dropped. A budget-partitioning threshold, so it lives in
# config per constitution §3 rather than inline. Must stay < REDLINE_PROMPT_MAX_CHARS.

REDLINE_REWRITE_MAX_CHARS: int = 4000
# Generated suggested_rewrite is truncated to this length before being written to
# ContractState, to bound persisted state size (spec §4.9). Larger than
# RISK_RATIONALE_MAX_CHARS (1000) because a rewritten clause is full replacement
# language, not a one-line explanation.

# ── Report thresholds ──────────────────────────────────────────────────────────
# Source: specs/009-report-agent/spec.md §6

REPORT_OUTPUT_DIR: str = "data/reports"
# Directory (backend/-relative, mirroring CRAG_KB_INDEX_PATH's anchoring) where
# ReportAgent writes serialized report files. Created if absent. (spec §6, D6)

REPORT_MD_FILENAME_TEMPLATE: str = "{document_id}.md"
# Human-readable Markdown report; report_path points here (D1). Deterministic on
# document_id so a re-run overwrites in place (D6, Edge Case 9).

REPORT_JSON_FILENAME_TEMPLATE: str = "{document_id}.json"
# Machine-readable JSON sibling written alongside the Markdown at the same stem
# (D1). Same deterministic-overwrite scheme (D6).

REPORT_EVIDENCE_TEXT_MAX_CHARS: int = 2000
# Per-row cap on evidence_trail `evidence_text` before it is written to state, to
# bound persisted state size (constitution §6; Edge Case 6). Mirrors the truncation
# discipline of RISK_RATIONALE_MAX_CHARS / REDLINE_REWRITE_MAX_CHARS.

# ── MCP delivery ───────────────────────────────────────────────────────────────
# Source: specs/010-mcp-delivery/spec.md §6

MCP_DELIVERY_ENABLED: bool = True
MCP_DRIVE_ENABLED: bool = True
MCP_GMAIL_ENABLED: bool = True

MCP_DELIVERY_RECIPIENT: str = os.getenv("CONTRACTSENTINEL_DELIVERY_RECIPIENT", "")
# Default Gmail recipient; "" → Gmail records FAILED ("no recipient configured")
# while Drive proceeds (D13). A runner may override per request (D4).

MCP_DRIVE_FOLDER_ID: Optional[str] = None
# Target Drive folder id. None → account's Drive root.

MCP_DRIVE_UPLOAD_FORMATS: tuple = ("md", "json")
# Which of Node 7's report files to upload. Both by default (AC-2).

MCP_GMAIL_ATTACH_REPORT: bool = True
# Attach the Markdown report for resilience even if the Drive link is unavailable.

MCP_DELIVERY_TIMEOUT_SECONDS: int = 60
# Per-attempt wall-clock timeout for one MCP tool call (AC-16).

MCP_DELIVERY_MAX_RETRIES: int = 2
# Bounded retries with exponential backoff for transient errors (AC-17, Edge Case 8).

GOOGLE_OAUTH_CREDENTIALS_PATH: str = "data/secrets/google_credentials.json"
GOOGLE_OAUTH_TOKEN_PATH: str = "data/secrets/google_token.json"
# OAuth client-secrets + cached-token paths (backend/-relative).
# Consumed by the MCP server layer, NOT the client step (D10). git-ignored.

# ── Runner / API layer ─────────────────────────────────────────────────────────
# Source: specs/011-pipeline-runner-api/spec.md §6.1

UPLOAD_DIR: str = "data/uploads"
# Directory (backend/-relative, mirroring REPORT_OUTPUT_DIR) where submitted contract
# files are persisted as document_path before the graph runs (constitution §6 — state
# minimality: the file is a reference, not embedded in state). Created if absent.

MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB
# Boundary reject → 413 (spec AC-16). Enforced while streaming the upload.

ALLOWED_UPLOAD_EXTENSIONS: frozenset = frozenset({".pdf", ".docx"})
# Boundary reject → 400 (spec AC-15). MIRRORS IngestAgent's ALLOWED_EXTENSIONS
# (ingest_agent.py); test_upload_extensions_match_ingest locks the two against drift.

RUNNER_WORKER_CONCURRENCY: int = 1
# Size of the shared background worker pool (spec D4). 1 because local Ollama serves one
# generation at a time; >1 would contend, not speed up. Excess submissions queue.

# ── Durable persistence (feature 012) ──────────────────────────────────────────
# Source: specs/012-durable-persistence/spec.md §6.1

JOB_STORE_DB_PATH: str = "data/job_store.db"
# Alembic-managed durable job store (spec D1). backend/-relative, mirroring
# REPORT_OUTPUT_DIR / UPLOAD_DIR. Holds the durable projection of JobRecord so a
# GET survives a process restart (spec AC-2; kills 011 EC-9). git-ignored.

CHECKPOINTER_DB_PATH: str = "data/checkpoints.db"
# LangGraph SqliteSaver file (spec D1). Owned by SqliteSaver.setup(), NEVER by
# Alembic. Serialized ContractState per super-step, keyed by thread_id
# (== job_id, spec D3). git-ignored.

CHECKPOINTER_ENABLED: bool = True
# When True the runner compiles the graph with the SqliteSaver (spec D7). Tests
# and the CLI may disable it to compile a checkpointer-less graph (011 behavior).

JOB_STORE_RETENTION_MAX: int = 500
# Insert-time row cap (spec D5). On insert, rows beyond this are pruned oldest-
# first by submitted_at and their checkpoint threads deleted, so the two stores
# never drift. Supersedes 011's JOB_REGISTRY_MAX (kept as an alias below).

STARTUP_RECOVERY_ENABLED: bool = True
# When True the lifespan enumerates the store and re-enqueues recoverable jobs
# (spec D8). Tests disable it to assert store state without auto-running jobs.

JOB_REGISTRY_MAX: int = JOB_STORE_RETENTION_MAX
# 011 alias — keep so no existing call site breaks; new code reads JOB_STORE_RETENTION_MAX.

CORS_ALLOWED_ORIGINS: tuple = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
# Browser origins granted CORS (spec D7). Default = the Vite dev-server origins the future
# frontend/ runs on; a cross-origin EventSource/fetch fails without this even on localhost.

API_BIND_HOST: str = "127.0.0.1"
API_BIND_PORT: int = 8000
# Uvicorn bind target (spec D1). Localhost-only; no auth. Overridable for local use.

# ── Dynamic dashboard (feature 018) ────────────────────────────────────────────
# Source: specs/018-dynamic-dashboard/spec.md §2.4 (D3/D7). Tunable — aggregation logic
# reads these, never hardcodes them (constitution §3).

PORTFOLIO_HEALTH_MEDIUM_WEIGHT: float = 0.5
# D3 — a medium finding counts as half a high in the derived health penalty:
# health% = round(100 * (1 - (high + WEIGHT*medium) / max(1, high+medium+low))).

PORTFOLIO_HEALTH_BAND_HEALTHY: int = 80
PORTFOLIO_HEALTH_BAND_ELEVATED: int = 50
# D3 band cutoffs: pct >= HEALTHY → "healthy"; >= ELEVATED → "elevated"; else "at_risk".

USAGE_TIMELINE_DAYS: int = 30
# D7 — the usage timeline returns this many UTC day-buckets (dense, zero-filled).

JOBS_LIST_DEFAULT_LIMIT: int = 20
JOBS_LIST_MAX_LIMIT: int = 100
# GET /api/jobs pagination: default page size and the clamp ceiling (spec EC-6).

# ── Authentication (feature 014) ───────────────────────────────────────────────
# Source: specs/014-auth-landing/spec.md §2.3 (D1–D2/D12–D13)

AUTH_COOKIE_NAME: str = "cs_session"
AUTH_SESSION_TTL_SECONDS: int = 7 * 24 * 3600  # D12 — 7 days
AUTH_COOKIE_SECURE: bool = False  # D1 — must be True behind TLS
AUTH_BCRYPT_ROUNDS: int = 12  # D2
AUTH_PASSWORD_MIN: int = 8
AUTH_PASSWORD_MAX: int = (
    128  # D2 — bcrypt 72-byte truncation neutralized by SHA-256 pre-hash
)
AUTH_SIGNUP_OPEN: bool = (
    True  # 019 — open signup is safe again: per-user isolation means a
)
# new account sees only its own empty workspace (was closed in 014 when data was shared).
# Set False to lock signup after provisioning.
AUTH_SECRET_FILE: str = (
    "data/auth_secret"  # D1 — persisted random secret if AUTH_SECRET unset
)
