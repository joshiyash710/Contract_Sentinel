"""
RedlineAgent — Node 6 of the ContractSentinel LangGraph pipeline.

Owns all three graph elements for Node 6:
  - is_redline_eligible: shared predicate (single source of truth, spec §7.2)
  - route_on_risk: graph-level conditional edge after risk_score (spec §7.1)
  - redline_agent: the "risk found" branch — drafts a suggested_rewrite per
    redline-eligible clause via one generative LLM call each
  - skip_redline: the "no risk" branch — lightweight passthrough (spec §7.4)

Constitution rules observed:
  §3  — all thresholds sourced from app.config (re-exposed as module-level names
          for monkeypatching in tests — same pattern as risk_score_agent.py)
  §5  — partial-update rule: redline_agent returns only clauses/current_node/
          node_timings, plus error_count:1 when the circuit breaker opens;
          skip_redline returns only current_node/node_timings
  §7  — implementation follows TDD cycle defined in tasks.md
  §8  — every LLM call uses OLLAMA_MODEL_NAME (generative); never OLLAMA_EMBED_MODEL_NAME

Reads from state:
    clauses, document_id, ingest_error

Writes to state (partial dict):
    redline_agent: clauses (per-clause suggested_rewrite for eligible findings),
                   current_node, node_timings
                   + error_count:1 IFF the circuit breaker opened this run
    skip_redline:  current_node, node_timings only

Does NOT write:
    document_id, extracted_text, ocr_used, ingest_error, report_path,
    evidence_trail, mcp_delivery_status, retry_budgets, risk_level, risk_rationale,
    or any Self-RAG/CRAG/Ingest field.
"""

import logging
import time
from typing import Optional

import app.config as _config

from app.graph.state import ContractState, ClauseType, ValidationStatus, RiskLevel
from app.graph.nodes.drafters.redline_drafter import draft_rewrite

logger = logging.getLogger("contractsentinel.redline")

# Re-expose as module-level names so tests can monkeypatch them.
# Read by bare name in node logic — never via _config.NAME — so monkeypatching works.
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
REDLINE_RISK_THRESHOLD = _config.REDLINE_RISK_THRESHOLD
REDLINE_TIMEOUT_SECONDS = _config.REDLINE_TIMEOUT_SECONDS
REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD = _config.REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD
REDLINE_PROMPT_MAX_CHARS = _config.REDLINE_PROMPT_MAX_CHARS
REDLINE_PROMPT_RATIONALE_RESERVE_CHARS = _config.REDLINE_PROMPT_RATIONALE_RESERVE_CHARS
REDLINE_REWRITE_MAX_CHARS = _config.REDLINE_REWRITE_MAX_CHARS


def is_redline_eligible(record: dict) -> bool:
    """True iff this clause should be redlined: VALIDATED AND risk_level in the
    configured threshold. Robust to risk_level being a RiskLevel enum or its str
    value (RiskLevel is a str-Enum → hash-equal); None → False.

    Called by BOTH route_on_risk AND redline_agent so they can never disagree
    about which clauses are eligible (spec §7.2, AC-32).
    """
    if record.get("final_status") != ValidationStatus.VALIDATED:
        return False
    return record.get("risk_level") in REDLINE_RISK_THRESHOLD


def route_on_risk(state: ContractState) -> str:
    """Graph-level conditional edge after risk_score.

    Returns 'redline' if the document has ≥1 redline-eligible clause,
    else 'skip_redline'. Pure — never mutates state (AC-7).
    """
    if state.get("ingest_error") is not None:
        return "skip_redline"                      # AC-4
    clauses = state.get("clauses", {})
    if any(is_redline_eligible(rec) for rec in clauses.values()):
        return "redline"                           # AC-1
    return "skip_redline"                          # AC-2/3


def redline_agent(state: ContractState) -> dict:
    """LangGraph Node 6 (RedlineAgent). Reads clauses/document_id/ingest_error; drafts
    a safer suggested_rewrite for each redline-eligible clause; returns partial dict:
    clauses (per-clause suggested_rewrite), current_node, node_timings, and
    error_count:1 ONLY when the circuit breaker opened."""
    start_time = time.monotonic()
    current_node = "redline"
    document_id = state.get("document_id", "unknown")

    # ── Defensive: skip if IngestAgent reported an error ──────────────────────
    if state.get("ingest_error") is not None:
        elapsed = time.monotonic() - start_time
        return {
            "clauses": {},
            "current_node": current_node,
            "node_timings": {current_node: elapsed},
        }

    clauses = state.get("clauses", {})

    # ── Guard: empty clauses dict ─────────────────────────────────────────────
    if not clauses:
        logger.warning(
            "RedlineAgent: no clauses to process for document_id=%s",
            document_id,
        )
        elapsed = time.monotonic() - start_time
        return {
            "clauses": {},
            "current_node": current_node,
            "node_timings": {current_node: elapsed},
        }

    # Circuit-breaker state: a single mutable dict so nested helpers can mutate
    # it without `nonlocal` (which would be needed for bare int/bool locals).
    cb = {"consecutive_failures": 0, "open": False, "tripped": False}
    clause_updates = {}

    # Spec §9 metric source — mirrors Node 5's level_counts
    counts = {
        "eligible": 0,
        "rewritten": 0,
        "failed": 0,
        "noop": 0,
        "empty_text": 0,
        "bulk_skipped": 0,
    }

    # Process clauses in document order (by position field)
    sorted_clauses = sorted(
        clauses.items(),
        key=lambda kv: kv[1].get("position", 0),
    )

    for clause_id, record in sorted_clauses:
        # ── Gate: only eligible clauses are drafted ───────────────────────────
        if not is_redline_eligible(record):
            continue  # OMIT the key — never attempted (AC-9/10)

        counts["eligible"] += 1

        # ── Edge Case 6: eligible finding with empty/whitespace text ──────────
        text = (record.get("text") or "").strip()
        if not text:
            logger.warning(
                "RedlineAgent: empty/whitespace clause text for clause_id=%s document_id=%s",
                clause_id,
                document_id,
            )
            clause_updates[clause_id] = {"suggested_rewrite": None}  # explicit None (R3)
            counts["empty_text"] += 1
            continue  # CIRCUIT-NEUTRAL: no _account call (AC-20a)

        # ── Post-circuit-open bulk skip: no LLM call ──────────────────────────
        if cb["open"]:
            clause_updates[clause_id] = {"suggested_rewrite": None}
            counts["bulk_skipped"] += 1
            continue  # CIRCUIT-NEUTRAL: no _account, no draft_rewrite (AC-20a)

        # ── One LLM call per eligible, non-empty, non-skipped clause ──────────
        rationale = record.get("risk_rationale")
        evidence = record.get("evidence_snippets")  # may be []/None — AC-26
        ct = _clause_type_value(record.get("clause_type"))

        result = draft_rewrite(
            text,
            rationale,
            evidence,
            ct,
            timeout_seconds=REDLINE_TIMEOUT_SECONDS,
            model_name=OLLAMA_MODEL_NAME,
            prompt_max_chars=REDLINE_PROMPT_MAX_CHARS,
            rationale_reserve=REDLINE_PROMPT_RATIONALE_RESERVE_CHARS,
        )

        _account(result, cb)

        if result is None:
            # LLM failure / timeout / empty output → fail-safe: no rewrite (AC-18/19)
            clause_updates[clause_id] = {"suggested_rewrite": None}
            counts["failed"] += 1
            rewrite_len = 0
            is_noop = False
            logger.warning(
                "RedlineAgent: drafting failed for clause_id=%s document_id=%s",
                clause_id,
                document_id,
            )
        else:
            rewrite = result[:REDLINE_REWRITE_MAX_CHARS]
            if len(result) > REDLINE_REWRITE_MAX_CHARS:
                logger.debug(
                    "RedlineAgent: rewrite truncated from %d to %d chars for clause_id=%s",
                    len(result),
                    REDLINE_REWRITE_MAX_CHARS,
                    clause_id,
                )
            clause_updates[clause_id] = {"suggested_rewrite": rewrite}
            counts["rewritten"] += 1
            rewrite_len = len(rewrite)
            # Compare the UNtruncated result so an echoed clause longer than
            # REDLINE_REWRITE_MAX_CHARS is still detected as a no-op (spec §9.6).
            is_noop = result.strip() == text.strip()
            if is_noop:
                counts["noop"] += 1

        # Per-clause structured log — reached ONLY via the draft_rewrite path (AC-9)
        # DO NOT log the rewrite text (up to 4000 chars) — log metadata only
        risk_level_val = record.get("risk_level")
        level_str = risk_level_val.value if isinstance(risk_level_val, RiskLevel) else str(risk_level_val)
        logger.info(
            "RedlineAgent clause processed",
            extra={
                "document_id": document_id,
                "clause_id": clause_id,
                "risk_level": level_str,
                "rewrite_len": rewrite_len,
                "success": result is not None,
                "is_noop": is_noop,
                "circuit_open": cb["open"],
            },
        )

    elapsed = time.monotonic() - start_time

    # Aggregate metrics log (spec §9) — fires UNCONDITIONALLY
    logger.info(
        "RedlineAgent completed",
        extra={
            **counts,
            "circuit_opened": cb["tripped"],
            "elapsed_seconds": round(elapsed, 4),
        },
    )

    out = {
        "clauses": clause_updates,
        "current_node": current_node,
        "node_timings": {current_node: elapsed},
    }
    if cb["tripped"]:
        out["error_count"] = 1  # health signal — at most once per run (spec §7.6)
    return out


def skip_redline(state: ContractState) -> dict:
    """LangGraph 'no risk' branch. Records that no redlining was needed; writes NO
    clause fields ('clause marked clean' is emergent — spec §7.4). No LLM calls."""
    start_time = time.monotonic()
    logger.info(
        "SkipRedline: no redline-eligible findings for document_id=%s",
        state.get("document_id", "unknown"),
    )
    return {
        "current_node": "skip_redline",
        "node_timings": {"skip_redline": time.monotonic() - start_time},
    }


def _account(result, cb: dict) -> None:
    """Update circuit-breaker state after a genuine LLM call result.

    None = LLM failure; any real rewrite string resets the consecutive counter.
    When the threshold of consecutive failures is reached and the circuit isn't
    already open, opens it and sets tripped=True so the health signal emits once.

    Called ONLY from the draft_rewrite path — never from the empty-text or
    bulk-skip paths, which are circuit-neutral (AC-20a).
    """
    if result is None:
        cb["consecutive_failures"] += 1
        if (
            cb["consecutive_failures"] >= REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD
            and not cb["open"]
        ):
            cb["open"] = True
            cb["tripped"] = True
            logger.warning(
                "RedlineAgent LLM circuit opened after %d consecutive failures — "
                "emitting suggested_rewrite: None for remaining eligible clauses this run",
                cb["consecutive_failures"],
            )
    else:
        cb["consecutive_failures"] = 0


def _clause_type_value(raw) -> Optional[str]:
    """Normalize clause_type to its string value for the drafting prompt.

    Accepts: ClauseType enum, str, or None. Returns Optional[str].
    Identical to Node 4/5's helper (risk_score_agent.py:246-256).
    """
    if isinstance(raw, ClauseType):
        return raw.value
    if isinstance(raw, str):
        return raw
    return None
