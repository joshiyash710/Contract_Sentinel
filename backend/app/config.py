"""
Shared configurable constants for ContractSentinel pipeline nodes.

All threshold values referenced by node logic must be defined here as named
constants — never hardcoded inline in any node — per
specs/000-constitution.md §3 (Configurable Thresholds Rule).

Future nodes (CRAG, Self-RAG, etc.) will add their own constants here.
"""

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

OLLAMA_MODEL_NAME: str = "qwen3:14b"
# The Ollama model identifier for LLM calls in the pipeline.
# Qwen3 14B runs locally via Ollama — no cloud API cost.
# Fits in ~10GB VRAM at Q4_K_M quantization (any 12–16GB GPU).
# Used by ClauseSplitterAgent for semantic refinement and clause_type inference.
# Future nodes (CRAG, Self-RAG, etc.) may also use this constant.

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

SELF_RAG_MAX_ATTEMPTS: int = 3
# Maximum number of ISSUP ("worth flagging") judgment attempts per clause, per
# constitution §2 ("retry on ISSUP fail, max 3 attempts"). First attempt + retries
# together may not exceed this. retry_count = attempts_taken - 1, so
# retry_count ∈ {0, 1, 2} at this default. Renames the old SELF_RAG_MAX_RETRIES
# placeholder (spec §8b Q2).

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
