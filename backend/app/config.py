"""
Shared configurable constants for ContractSentinel pipeline nodes.

All threshold values referenced by node logic must be defined here as named
constants — never hardcoded inline in any node — per
specs/000-constitution.md §3 (Configurable Thresholds Rule).

Future nodes (CRAG, Self-RAG, etc.) will add their own constants here.
"""

import os
from typing import Optional

from dotenv import load_dotenv

# Feature 046: load backend/.env (GROQ_API_KEY etc.) BEFORE any os.getenv read below. Idempotent;
# no-op if .env is absent. Real process env vars still take precedence (load_dotenv does not override).
load_dotenv()

from app.graph.state import RiskLevel


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean env override (feature 032). '1/true/yes/on' → True, '0/false/no/off' → False."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Read an integer env override (feature 032); falls back to default on unset/unparseable."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    """Read a string env override (feature 049); falls back to default on unset/blank, else trims.
    Companion to _env_bool/_env_int for prod URL config (OAuth redirect, frontend URLs)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()

# ── IngestAgent thresholds ─────────────────────────────────────────────────────
# Source: specs/003-ingest-agent/spec.md §6
MIN_TEXT_LENGTH_THRESHOLD: int = 50  # chars; below → force OCR
MIN_CHAR_DENSITY_THRESHOLD: int = 100  # chars/page; below → force OCR
OCR_LOW_CONFIDENCE_THRESHOLD: float = (
    0.6  # normalised 0–1; below → flaggable downstream
)
INGEST_TIMEOUT_SECONDS: int = 60  # wall-clock seconds for parse_pdf / parse_docx

INGEST_STRIP_DOCUMENT_CHROME_ENABLED: bool = True
# Master switch (feature 044). When True, IngestAgent removes recognizable EDGAR page-footer chrome
# (`Source: <COMPANY>, <FORM>, <DATE>` + an immediately-adjacent bare page-number line) from
# extracted_text before clause segmentation. False ⇒ byte-for-byte today's extracted_text. Reversible.

# ── ClauseSplitterAgent thresholds ─────────────────────────────────────────────
# Source: specs/004-clause-splitter-agent/spec.md §6

OLLAMA_MODEL_NAME: str = "qwen3:8b"
# Generative model. qwen3:8b (~6GB) does NOT fit fully in the 6GB laptop GPU (RTX 4050) — Windows
# reserves ~1GB for display so only ~5GB VRAM is free — so Ollama loads it as a ~70% GPU / 30% CPU
# split (verified 2026-07-31: 4.1GB on GPU, resident, produces genuine judgments). The split is
# slower than full-GPU but stable; it avoids the all-GPU PTX/CUDA crash that happens when the model
# is forced entirely onto the GPU. qwen3:4b is the lighter fallback if RAM/VRAM is too tight to hold
# the split. §3-tunable. Requires ~1.6GB free RAM to load the host buffer.
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

# ── LLM provider seam (feature 046) — generation via Groq, embeddings stay on Ollama (§8) ─────────
# When LLM_PROVIDER="groq", the 5 generative chat call sites route to Groq's API; bge-m3 embeddings
# ALWAYS stay on local Ollama (constitution §8). Default "ollama" ⇒ byte-for-byte today's behavior.
# GROQ_* are env-read so the deploy sets them without a code change. NEVER log GROQ_API_KEY.
# See specs/046 (incl. the data-egress privacy posture) and docs/DEPLOYMENT.md.
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama").strip().lower()  # "ollama" | "groq"
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_REASONING_EFFORT: str = os.getenv("GROQ_REASONING_EFFORT", "low")
GROQ_MAX_RETRIES: int = _env_int("GROQ_MAX_RETRIES", 2)

# ── Prompt-injection defense (feature 035, Security Tier 2) ──────────────────────
# Source: specs/035-prompt-injection-defense/{spec,plan}.md. Within-node prompt hardening across the
# 4 generative chat() sites; no node/edge/state change. Read ONCE in app/llm/prompt_guard.py.
PROMPT_INJECTION_DEFENSE_ENABLED: bool = True
# Master reversible lever. True → untrusted clause/evidence/rationale is fenced in a wrap_untrusted
# block inside a `user` message and trusted instructions move to a `system` message. False → the exact
# pre-035 single-`user`-message prompts (byte-identical), for an accuracy-regression escape hatch.
PROMPT_GUARD_SENTINEL_BYTES: int = 8
# Entropy (bytes) of the per-call random nonce in the untrusted-block delimiter; token_hex → 16 hex chars.

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

CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS: bool = False
# Feature 045. When False (default), the regex splitter does NOT split on enumerated sub-list markers
# "(a)"/"(ii)"/"a." — those sub-items stay attached to their governing clause (measured: recovers
# material obligations buried in sub-items, e.g. a non-compete in item (f) of a "shall not:" list, and
# yields healthier segmentation — 187→117 clauses on a real doc, short fragments halved). True ⇒
# byte-for-byte today's segmentation (sub-lists split as before). Reversible.

CLAUSE_SPLITTER_LLM_MAX_CLAUSES: int = 40
# §3 latency lever A: above this regex-clause count, ClauseSplitter skips the LLM refinement
# (refine_with_llm) and uses the regex splitter output directly. The real corpus clusters into
# ~8-clause (normal) and ~185-clause (large) documents; 40 keeps full LLM clause typing/boundary
# quality for normal contracts while gating only the large-doc outliers where the refine call is
# slowest. Tunable against real node_timings.

DETERMINISTIC_CLAUSE_TYPING_ENABLED: bool = False
# Master switch (feature 042). When True, ClauseSplitter fills clause_type from a deterministic
# keyword tagger for any clause the LLM refinement left None (025 Lever-A skip on >40-clause docs,
# or an off-schema LLM failure). Revives the 027 recall floor on large docs with NO LLM dependence.
# False ⇒ byte-for-byte today's behavior (previously-None clauses stay None). Reversible (D5).
#
# SHIPPED DEFAULT False (AC-7 merge gate, 2026-08-19). The mechanism works — a 6-doc large-subset
# measure showed 027 floor-rescues 0→66 (all 6 docs) and recall 15.2%→32.6% (+17.4pp). But the
# precision cost FAILED the plan §6 gate: false-flag 15.0%→32.5% (+17.5pp ≫ the +5pp cap, and the
# recall gain did not exceed the false-flag gain) — a ~1:1 trade, not a net win. Over-broad phrases
# (IP terms hitting clean license-grants; termination terms hitting clean renewal/expiration) are the
# main culprits. Feature ships present + OFF, pending phrase-map tightening + a re-measure.

# Ordered map: ClauseType.value -> tuple of lowercase phrase patterns. ONLY the recall-floor types
# (SELF_RAG_RECALL_FLOOR_TYPES) — typing a non-floor type has no floor effect (D2). CONSERVATIVE,
# high-precision multi-word legal phrases (a floor-typed clause is VALIDATED even if ISSUP would
# discard, so over-matching = false flags, D3). Order = tie-break for a multi-match clause (EC-1).
DETERMINISTIC_CLAUSE_TYPE_PATTERNS: tuple = (
    ("confidentiality", ("confidential information", "non-disclosure", "shall not disclose",
                          "keep confidential", "proprietary information")),
    ("liability",       ("limitation of liability", "shall not be liable", "in no event shall",
                         "indemnif", "hold harmless", "consequential damages", "liquidated damages")),
    ("intellectual_property", ("intellectual property rights", "proprietary rights", "hereby assigns",
                               "assignment of intellectual property",
                               "ownership of the intellectual property",
                               "all right, title and interest in and to the intellectual property",
                               "work product")),
    ("termination",     ("termination of this agreement", "terminate this agreement",
                         "survive termination", "expiration or termination", "right to terminate")),
)
# ALL patterns are CONSERVATIVE MULTI-WORD LEGAL PHRASES (D3). Deliberately NO bare single words like
# "patent"/"copyright"/"trademark" (they appear in definitions/representations/license/notices clauses
# that are NOT IP-ownership risks → would be floor-VALIDATED as false flags). Deliberately NO generic
# fragments like "assignment of" (matches "assignment of this Agreement" = anti_assignment boilerplate)
# or "ownership of the" — each IP phrase carries its own IP context. NOTE: the four keys are exactly
# SELF_RAG_RECALL_FLOOR_TYPES; the tagger emits only these four ClauseType.value keys.

CLAUSE_SPLITTER_LLM_EMIT_TEXT: bool = False
# §3 latency lever F (feature 029): when False (default), the ClauseSplitter refinement LLM returns
# index-grouping + clause_type metadata ONLY (no full clause text), and the refiner reassembles each
# clause's text locally from the regex segments. This avoids re-generating the entire document as
# output tokens (the ~60-70s cost of the pre-029 call). When True, the node uses the pre-029
# text-re-emitting prompt byte-for-byte (fully reversible). Regex boundaries are the finest unit in
# grouping mode (no intra-segment splitting); any grouping that is not an exact partition of the
# input segments falls back to regex output.

CLAUSE_SPLITTER_LLM_NUM_PREDICT: int = 4096
# §3: output-token cap for the refinement call when EMIT_TEXT is False (metadata is small). Replaces
# the previously hardcoded 4096; the emit-text path reverts to 4096. Tunable — raise if a real doc's
# grouping JSON truncates (which would trigger the regex fallback). Feature 047: raised 1024→4096 so
# large-doc index-only grouping output (and, on Groq reasoning models, shared reasoning tokens) is not
# truncated; index-only JSON stays compact so the higher cap is cheap.

CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING: bool = False
# §3 feature 047. When True, the grouping-mode parser applies the model's VALID partial output — its
# merges + clause_type — and fills any un-referenced/out-of-range/duplicate index with a passthrough
# regex singleton, instead of discarding the whole response on a non-exact partition; reviving the
# model's clause_type on large docs re-arms the 027 recall floor. False (default) ⇒ byte-for-byte the
# strict exact-partition behavior (a non-partition response → ValueError → regex fallback).
# SHIPPED DEFAULT False (AC-10, specs/047-.../RESULTS.md): the mechanism is proven (probe: gpt-oss types
# floor-types correctly on partial groupings) but NO end-to-end recall gain was measurable — the target
# case (gpt-oss partial partitions on large docs) is starved by Groq's 200K-tok/day cap, and the local
# qwen3:4b A/B produced exact partitions (tolerant = strict, no delta). 042 gate unmet → ship OFF,
# reversible; flip True once a gpt-oss large-doc run confirms the recall gain.

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

SELF_RAG_MERGE_JUDGMENTS: bool = False
# §3 latency lever C (feature 029): when True, the evidence-present Self-RAG path issues ONE
# combined-judgment LLM call returning all three verdicts (relevance + isrel + issup) instead of up to
# three sequential calls, cutting up to 3N generative round-trips to N. The node applies the same
# decision logic (discard-vs-validate, 027 recall-floor short-circuit, fail-open on failure) to the
# three merged verdicts. When False, the node uses the sequential three-call path byte-for-byte.
# Note: circuit-breaker accounting is per-LLM-call, so with merging on there is one accounting event
# per clause instead of up to three. Retries (SELF_RAG_MAX_ATTEMPTS > 1) require this to be False — a
# merged issup=False is terminal.
#
# DEFAULT False (feature 029 merge decision, 2026-07-28): the code ships but is dormant. The measured
# self_rag latency gain was modest (−10..−17%) and the merged prompt is slightly more lenient — on the
# seed corpus it recovered a missed clause (recall 90.9→100%) but added false flags (precision
# 90.9→78.6%), F1 ~flat. Since that changes analysis OUTPUT on thin (n=1, 14-clause) evidence, it is
# held off until a larger expert-labeled corpus confirms the trade. Flip to True to enable. Lever F
# (clause_splitter) ships ON — it is accuracy-neutral and carries the bulk of the latency win.

SELF_RAG_MERGED_NUM_PREDICT: int = 384
# §3: output-token cap for the combined judgment call. Larger than the single-verdict reflectors' 256
# so the 3-verdict + short-reason JSON object cannot truncate. Tunable — a truncated object parses to a
# whole-call failure and fail-opens.

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

# Env-overridable so a local/offline smoke can skip the Google Drive/Gmail push (which otherwise
# blocks job completion on a long network timeout when Google isn't reachable). Default stays True.
MCP_DELIVERY_ENABLED: bool = _env_bool("MCP_DELIVERY_ENABLED", True)
MCP_DRIVE_ENABLED: bool = _env_bool("MCP_DRIVE_ENABLED", True)
MCP_GMAIL_ENABLED: bool = _env_bool("MCP_GMAIL_ENABLED", True)

MCP_DELIVERY_RECIPIENT: str = os.getenv("CONTRACTSENTINEL_DELIVERY_RECIPIENT", "")
# Default Gmail recipient; "" → Gmail records FAILED ("no recipient configured")
# while Drive proceeds (D13). A runner may override per request (D4).

MCP_DRIVE_FOLDER_ID: Optional[str] = None
# Target Drive folder id. None → account's Drive root.

MCP_DRIVE_UPLOAD_FORMATS: tuple = ("pdf", "json")
# Which report files to upload to Drive. Feature 030: the branded PDF supersedes the raw md for
# humans; json stays as the machine-readable record. (Was ("md","json") pre-030.)

MCP_GMAIL_ATTACH_REPORT: bool = True
# Attach the report file for resilience even if the Drive link is unavailable.

# ── Feature 030 — professional report delivery (Phase 1: PDF + SaaS HTML email) ──
# All delivery-layer, reversible: MCP_REPORT_PDF_ENABLED=False + MCP_GMAIL_ATTACH_FORMAT="md"
# restores the pre-030 plain-text email + Markdown attachment. §3 named constants.

MCP_GMAIL_ATTACH_FORMAT: str = "pdf"
# Which file to attach to the delivery email. "pdf" = the branded report (default); "md" reverts to
# the pre-030 Markdown attachment.

MCP_REPORT_PDF_ENABLED: bool = True
# Master toggle for rendering the branded PDF at delivery time (reportlab). False → no PDF; delivery
# falls back to the pre-030 .md attachment + plain-text email.

REPORT_PDF_CLAUSE_MAX_CHARS: int = 2000
REPORT_PDF_RATIONALE_MAX_CHARS: int = 1500
REPORT_PDF_REWRITE_MAX_CHARS: int = 4000
# Per-field truncation caps for the PDF renderer, bounding document size (mirrors the report's own
# char-cap discipline). Tunable §3.

REPORT_BRAND_NAME: str = "ContractSentinel"
REPORT_BRAND_ACCENT_HEX: str = "#1e293b"  # professional navy (slate-800)
REPORT_BRAND_FOOTER: str = (
    "Automated contract-risk analysis — review with qualified counsel."
)
# Text/CSS wordmark branding for the PDF + HTML email (no binary logo asset in Phase 1).

# ── Feature 033 — Drive folder + human-readable report naming (delivery-layer, reversible) ──
# MCP_DRIVE_HUMAN_READABLE_NAMES=False restores pre-033 document_id names; MCP_DRIVE_FOLDER_NAME=None/""
# restores upload to Drive root. All §3 named constants.
MCP_DRIVE_FOLDER_NAME: Optional[str] = "ContractSentinel"
# Drive folder to find-or-create and upload reports into. None/"" → root (pre-033). An explicitly set
# MCP_DRIVE_FOLDER_ID (below) still takes precedence and skips find-or-create.
MCP_DRIVE_HUMAN_READABLE_NAMES: bool = True
# True → Drive/email report names like "<Contract> — Risk Report (<id>).pdf"; False → document_id names.
MCP_DRIVE_REPORT_NAME_TEMPLATE: str = "{stem} — Risk Report ({disc})"
# {stem} = sanitized original filename (no extension); {disc} = uniqueness discriminator (Decision 1).
MCP_DRIVE_NAME_DISCRIMINATOR_CHARS: int = 6
# Number of leading document_id chars used for {disc}.
MCP_DRIVE_NAME_MAX_STEM_CHARS: int = 120
# Cap on {stem} length to avoid pathological Drive names.

MCP_DELIVERY_TIMEOUT_SECONDS: int = 60
# Per-attempt wall-clock timeout for one MCP tool call (AC-16).

MCP_DELIVERY_MAX_RETRIES: int = 2
# Bounded retries with exponential backoff for transient errors (AC-17, Edge Case 8).

GOOGLE_OAUTH_CREDENTIALS_PATH: str = "data/secrets/google_credentials.json"
GOOGLE_OAUTH_TOKEN_PATH: str = "data/secrets/google_token.json"
# OAuth client-secrets + cached-token paths (backend/-relative).
# Consumed by the MCP server layer, NOT the client step (D10). git-ignored.
# NOTE (feature 031): these remain the CENTRAL desktop client + token, used for the
# central Gmail send. Per-user Drive uses the separate web client below.

# ── Feature 031 — per-user Google Drive (per-user OAuth) ─────────────────────────
# §3 named constants; reversible via PER_USER_DRIVE_ENABLED. Authorized by the §2
# amendment (2026-07-28, feature 031): per-user Drive only; Gmail stays central.

PER_USER_DRIVE_ENABLED: bool = True
# Master toggle. False → delivery ignores per-user tokens and uses the central token
# (pre-031 behavior); fully reversible.

GOOGLE_OAUTH_REDIRECT_URI: str = _env_str(
    "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/integrations/google/callback"
)
# The web OAuth callback (backend, spec §6 Q1/Q2). Must match the authorized redirect URI
# registered on the Web OAuth client in GCP Console. Prod needs its own registered URI.
# Feature 049: env-overridable — set to https://api.<domain>/api/integrations/google/callback in prod.

GOOGLE_DRIVE_OAUTH_SCOPES: tuple = ("https://www.googleapis.com/auth/drive.file",)
# Per-user connect scope: create/manage only app-created files in the user's own Drive.

GOOGLE_OAUTH_WEB_CREDENTIALS_PATH: str = "data/secrets/google_web_credentials.json"
# Web-application OAuth client secrets (distinct from the central desktop client above).
# git-ignored; the owner registers the client + redirect URI in GCP Console.

FRONTEND_INTEGRATIONS_URL: str = _env_str(
    "FRONTEND_INTEGRATIONS_URL", "http://localhost:3000/integrations"
)
# Where the OAuth callback 302-redirects the browser after connect/disconnect.
# Feature 049: env-overridable — set to the deployed frontend /integrations page in prod.

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

_DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _env_origin_tuple(name: str, default: tuple) -> tuple:
    """Feature 048: comma-separated CORS origin allowlist from env; trims each, drops empties.
    If the env var is unset OR parses to zero non-empty origins, return `default` — never an empty
    allowlist (an empty tuple would reject every browser origin, breaking the app)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    parsed = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parsed if parsed else default


CORS_ALLOWED_ORIGINS: tuple = _env_origin_tuple(
    "CORS_ALLOWED_ORIGINS", _DEFAULT_CORS_ALLOWED_ORIGINS
)
# Browser origins granted CORS (spec D7). Default = the Vite dev-server origins the future
# frontend/ runs on; a cross-origin EventSource/fetch fails without this even on localhost.
# Feature 048: env-overridable (comma-separated) so a cross-origin deploy (e.g. the Vercel frontend
# origin) can be granted CORS without a code change; unset ⇒ the localhost default above.

API_BIND_HOST: str = "127.0.0.1"
API_BIND_PORT: int = 8000
# Uvicorn bind target (spec D1). Localhost-only; no auth. Overridable for local use.

# ── Upload content-type (magic-byte) validation (feature 037, Security Tier 2) ───
UPLOAD_MAGIC_BYTE_CHECK_ENABLED: bool = True
# When True, the upload route verifies the file's leading bytes match its extension (not just the
# extension), rejecting a mislabeled/hostile file (e.g. an executable named .pdf) with 400. Reversible.
UPLOAD_MAGIC_PREFIXES: dict = {
    ".pdf": (b"%PDF",),
    ".docx": (b"PK",),  # OOXML is a ZIP container — all zip variants start with "PK"
}

# ── Security response headers (feature 037, Security Tier 2) ─────────────────────
SECURITY_HEADERS_ENABLED: bool = True
# When True, a middleware adds hardening headers to every response. Reversible.
SECURITY_HSTS_ENABLED: bool = _env_bool("SECURITY_HSTS_ENABLED", False)
# HSTS is only meaningful behind TLS and can lock a browser onto https for a domain — default OFF for
# local plaintext-HTTP dev; set True in a TLS deployment.
SECURITY_HEADERS: dict = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # The API returns only JSON; a strict CSP that forbids any active content is safe here and blunts
    # reflected-content attacks. The Next.js frontend serves its own pages/CSP separately.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

# ── Dynamic dashboard (feature 018) ────────────────────────────────────────────
# Source: specs/018-dynamic-dashboard/spec.md §2.4 (D3/D7). Tunable — aggregation logic
# reads these, never hardcodes them (constitution §3).

PORTFOLIO_HEALTH_MEDIUM_WEIGHT: float = 0.5
# D3 — a medium finding counts as half a high in the derived health penalty:
# health% = round(100 * (1 - (high + WEIGHT*medium) / max(1, high+medium+low))).

# ── Honest LLM-failure surfacing (feature 038, Security Tier 2) ──────────────────
# Source: specs/038-honest-llm-failure-surfacing/{spec,plan,tasks}.md. Surfaces the fail-safe /
# circuit-breaker signal RiskScoreAgent already computes so a degraded (all-fail-safe) report is
# honestly flagged instead of masquerading as genuine analysis. No node/edge change.
HONEST_FAILURE_SURFACING_ENABLED: bool = True
# Master reversible lever. True → RiskScoreAgent writes per-clause `is_failsafe`, the report model
# carries `analysis_degraded`/`failsafe_count`/per-finding `is_failsafe`, and the renderers/frontend
# show a degraded-analysis banner + "(auto)" tags. False → byte-identical pre-038 behavior (the
# field/flags are never written; no banner/tag anywhere).
ANALYSIS_DEGRADED_FAILSAFE_FRACTION: float = 0.5
# Tunable (§3). assemble_report marks a report degraded when the risk-score circuit breaker tripped
# (error_count >= 1) OR the fraction of validated findings that are fail-safe is >= this value.
# 0.5 avoids crying wolf on one isolated empty-text clause while catching partial outages.

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

# ── Session/cookie hardening (feature 032, W2) — SUPERSEDES 014's TTL/Secure ─────
# Source: specs/032-security-hardening-tier1/{spec,plan}.md §2.3/§3. Env-overridable (§3).
AUTH_COOKIE_SECURE: bool = _env_bool("AUTH_COOKIE_SECURE", True)
# 032: default True (was False). A Secure cookie is dropped by browsers over plain HTTP, so this
# REQUIRES TLS in front of the app. For local plaintext-HTTP dev set AUTH_COOKIE_SECURE=False (EC-10).

# Feature 048: cross-origin cookie SameSite — env-overridable. Default "lax" = byte-identical to
# pre-048. Set "none" for a cross-site frontend↔backend deploy (e.g. *.vercel.app ↔ VM); the browser
# only attaches a cross-site cookie when it is SameSite=None (and requires Secure with it).
_ALLOWED_SAMESITE = ("lax", "strict", "none")


def _env_samesite(name: str, default: str = "lax") -> str:
    """Read the cookie SameSite policy from env; unrecognized ⇒ safe default (lax)."""
    val = os.getenv(name, default).strip().lower()
    return val if val in _ALLOWED_SAMESITE else default


def _validate_samesite_secure(samesite: str, secure: bool) -> None:
    """Feature 048 safety invariant (spec G4/AC-7): a SameSite=None cookie is dropped by browsers
    unless it is also Secure. Fail loudly at boot rather than ship a login cookie the browser
    silently discards. Named function so it is testable directly (no config reload)."""
    if samesite == "none" and not secure:
        raise ValueError(
            "AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=True "
            "(browsers drop a SameSite=None cookie without the Secure attribute)."
        )


AUTH_COOKIE_SAMESITE: str = _env_samesite("AUTH_COOKIE_SAMESITE", "lax")
_validate_samesite_secure(AUTH_COOKIE_SAMESITE, AUTH_COOKIE_SECURE)  # boot-time guard
AUTH_SESSION_TTL_SECONDS: int = _env_int("AUTH_SESSION_TTL_SECONDS", 8 * 3600)
# 032: absolute session lifetime cap = 8h (was 7 days). Max a session can live regardless of activity.
AUTH_IDLE_TIMEOUT_SECONDS: int = _env_int("AUTH_IDLE_TIMEOUT_SECONDS", 30 * 60)
# 032: sliding idle window = 30 min. No authenticated request within this window → session rejected.
# Refreshed on each authenticated request, never exceeding the absolute cap above.
AUTH_CLOCK_SKEW_SECONDS: int = 60
# 032: tolerance applied to exp/aexp checks so small clock skew doesn't mis-expire (EC-5).

# ── Encryption at rest for OAuth tokens (feature 032, W1) ────────────────────────
# Authorized by the §2 amendment (2026-07-31, feature 032). Fernet symmetric key; NEVER logged.
ENCRYPTION_KEY_ENV: str = "CONTRACTSENTINEL_ENCRYPTION_KEY"
# Name of the env var holding a base64 Fernet key. Takes precedence over the key file.
ENCRYPTION_KEY_FILE: str = "data/encryption_key"
# Persisted Fernet key if the env var is unset; generated + written 0600 on first run
# (mirrors AUTH_SECRET_FILE bootstrap). Losing this orphans stored tokens → users re-connect.

# ── Contract encryption at rest (feature 036) ───────────────────────────────────
# Source: specs/036-contract-encryption-at-rest/. Encrypts the uploaded contract file bytes on disk
# (UPLOAD_DIR) with the same Fernet key; decrypt-to-tempfile at ingest. Reversible.
CONTRACT_ENCRYPTION_AT_REST_ENABLED: bool = True
# True → uploaded contracts stored as Fernet ciphertext, decrypted to a short-lived temp file for
# parsing. False → pre-036 plaintext store + in-place parse. Legacy plaintext uploads tolerated either way.

# ── Login/signup rate-limiting & account lockout (feature 032, W3) ───────────────
# Source: specs/032-security-hardening-tier1/{spec,plan}.md §2.4/§4. All env-overridable (§3).
AUTH_RATE_LIMIT_MAX: int = _env_int("AUTH_RATE_LIMIT_MAX", 10)
AUTH_RATE_LIMIT_WINDOW_SECONDS: int = _env_int("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60)
# Per-IP: at most MAX login/signup/password attempts per WINDOW seconds → else 429 + Retry-After.
AUTH_LOCKOUT_MAX_FAILURES: int = _env_int("AUTH_LOCKOUT_MAX_FAILURES", 5)
AUTH_LOCKOUT_WINDOW_SECONDS: int = _env_int("AUTH_LOCKOUT_WINDOW_SECONDS", 15 * 60)
AUTH_LOCKOUT_DURATION_SECONDS: int = _env_int("AUTH_LOCKOUT_DURATION_SECONDS", 15 * 60)
# Per-account: MAX_FAILURES consecutive failed logins within WINDOW → account locked (429) for
# DURATION seconds, even if the next password is correct (AC-13). A success resets the counter.

# ── Forgot-password / reset link (feature 034) ───────────────────────────────────
# Source: specs/034-forgot-password/{spec,plan}.md. All §3 named constants; env-overridable.
AUTH_RESET_TOKEN_TTL_SECONDS: int = _env_int("AUTH_RESET_TOKEN_TTL_SECONDS", 30 * 60)  # 30 min (Decision 3)
AUTH_RESET_TOKEN_BYTES: int = 32  # secrets.token_urlsafe(32) → ~43-char, ~256-bit token (Decision 1)
AUTH_RESET_EMAIL_COOLDOWN_SECONDS: int = _env_int("AUTH_RESET_EMAIL_COOLDOWN_SECONDS", 60)
# Per-email: at most one reset email per COOLDOWN seconds (mailbomb protection, AC-7).
FRONTEND_RESET_URL: str = os.getenv("FRONTEND_RESET_URL", "http://localhost:3000/reset")
# Base URL of the frontend /reset page embedded in the emailed link; env-overridable for non-dev deploys.
