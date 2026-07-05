"""
RiskScore Agent — Node 5 of the ContractSentinel LangGraph pipeline.

Responsibility: assign Low/Medium/High severity to each validated finding
(final_status == VALIDATED) produced by Self-RAG validation (Node 4), together
with a short risk_rationale explaining the assignment.

Constitution rules observed:
  §3  — all thresholds sourced from app.config (re-exposed as module-level names
          for monkeypatching in tests — same pattern as self_rag_validation_agent.py)
  §5  — partial-update rule: returns only clauses, current_node, node_timings,
          plus error_count:1 in the one case the circuit breaker opens (spec §4.5)
  §7  — implementation follows TDD cycle defined in tasks.md
  §8  — every LLM call uses OLLAMA_MODEL_NAME (generative); never OLLAMA_EMBED_MODEL_NAME

Reads from state:
    clauses, document_id, ingest_error

Writes to state (partial dict):
    clauses (per-clause risk_level + risk_rationale for VALIDATED findings),
    current_node, node_timings
    + error_count:1 IFF the circuit breaker opened this run

Does NOT write:
    document_id, extracted_text, ocr_used, ingest_error, report_path,
    evidence_trail, mcp_delivery_status, retry_budgets, suggested_rewrite
"""

import logging
import time
from typing import Optional

import app.config as _config

from app.graph.state import ContractState, ClauseType, ValidationStatus
from app.graph.nodes.scorers.risk_scorer import score_risk

logger = logging.getLogger("contractsentinel.risk_score")

# Re-expose as module-level names so tests can monkeypatch them.
# Read by bare name in node logic — never via _config.NAME — so monkeypatching works.
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
RISK_SCORE_TIMEOUT_SECONDS = _config.RISK_SCORE_TIMEOUT_SECONDS
RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD = (
    _config.RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD
)
RISK_SCORE_PROMPT_MAX_CHARS = _config.RISK_SCORE_PROMPT_MAX_CHARS
RISK_RATIONALE_MAX_CHARS = _config.RISK_RATIONALE_MAX_CHARS
RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE = _config.RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE


def risk_score_agent(state: ContractState) -> dict:
    """LangGraph Node 5. Reads clauses/document_id/ingest_error; scores only
    VALIDATED findings; returns partial dict: clauses (per-finding risk_level +
    risk_rationale), current_node, node_timings, and error_count:1 ONLY when the
    circuit breaker opened."""
    start_time = time.monotonic()
    current_node = "risk_score"
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
            "RiskScoreAgent: no clauses to score for document_id=%s",
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

    # Process clauses in document order (by position field)
    sorted_clauses = sorted(
        clauses.items(),
        key=lambda kv: kv[1].get("position", 0),
    )

    level_counts = {"low": 0, "medium": 0, "high": 0, "failsafe": 0}

    for clause_id, record in sorted_clauses:
        final_status = record.get("final_status")

        # Skip DISCARDED / None — no update, no LLM call (AC-2, AC-3, AC-10)
        if final_status != ValidationStatus.VALIDATED:
            continue

        text = (record.get("text") or "").strip()

        # Edge Case 6: empty/whitespace text → fail-safe default (circuit-neutral)
        if not text:
            logger.warning(
                "RiskScore: empty/whitespace clause text for clause_id=%s document_id=%s",
                clause_id,
                document_id,
            )
            # CIRCUIT-NEUTRAL: no _account call (AC-14a)
            clause_updates[clause_id] = _failsafe(
                "clause text was empty; assigned default severity"
            )
            level_counts["failsafe"] += 1
            continue

        # Post-circuit-open bulk default: no LLM call (circuit-neutral)
        if cb["open"]:
            clause_updates[clause_id] = _failsafe(
                "scoring backend unavailable; assigned default severity"
            )
            level_counts["failsafe"] += 1
            continue

        evidence = record.get("evidence_snippets")  # may be []/None — AC-20
        ct = _clause_type_value(record.get("clause_type"))

        # One LLM call per validated finding
        result = score_risk(
            text,
            evidence,
            ct,
            RISK_SCORE_TIMEOUT_SECONDS,
            OLLAMA_MODEL_NAME,
            RISK_SCORE_PROMPT_MAX_CHARS,
        )

        _account(result, cb)

        if result is None:
            # LLM failure / unparseable output → fail-safe (AC-12/13)
            clause_updates[clause_id] = _failsafe(
                "scoring failed; assigned default severity"
            )
            level_counts["failsafe"] += 1
        else:
            level, rationale = result
            truncated = rationale[:RISK_RATIONALE_MAX_CHARS]
            if len(rationale) > RISK_RATIONALE_MAX_CHARS:
                logger.debug(
                    "RiskScore: rationale truncated from %d to %d chars for clause_id=%s",
                    len(rationale),
                    RISK_RATIONALE_MAX_CHARS,
                    clause_id,
                )
            clause_updates[clause_id] = {
                "risk_level": level,
                "risk_rationale": truncated,
            }
            level_counts[level.value] += 1

        # Reached only via the score_risk path; text is guaranteed non-empty here
        # and the level is always a RiskLevel, so is_failsafe reduces to result is None.
        logger.info(
            "RiskScore clause scored",
            extra={
                "document_id": document_id,
                "clause_id": clause_id,
                "risk_level": clause_updates[clause_id]["risk_level"].value,
                "is_failsafe": result is None,
                "circuit_open": cb["open"],
            },
        )

    elapsed = time.monotonic() - start_time
    total_validated = len(clause_updates)
    total_skipped = len(sorted_clauses) - total_validated

    # Aggregate metrics log (spec §9) — fires unconditionally
    logger.info(
        "RiskScoreAgent completed",
        extra={
            "document_id": document_id,
            "validated_scored": total_validated,
            "clauses_skipped": total_skipped,
            "level_low": level_counts["low"],
            "level_medium": level_counts["medium"],
            "level_high": level_counts["high"],
            "failsafe_count": level_counts["failsafe"],
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
        out["error_count"] = 1  # health signal — at most once per run (spec §7.4)
    return out


def _failsafe(reason: str) -> dict:
    """Return a fail-safe clause update with the default level and an [auto] rationale."""
    return {
        "risk_level": RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE,
        "risk_rationale": (
            f"[auto] {reason} (default={RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE.value})"
        ),
    }


def _account(result, cb: dict) -> None:
    """Update circuit-breaker state after a genuine LLM call result.

    None = LLM failure; any real (level, rationale) resets the consecutive counter.
    When the threshold of consecutive failures is reached and the circuit isn't
    already open, opens it and sets tripped=True so the health signal emits once.

    Called ONLY from the score_risk path — never from the empty-text or bulk-default
    paths, which are circuit-neutral (AC-14a).
    """
    if result is None:
        cb["consecutive_failures"] += 1
        if (
            cb["consecutive_failures"] >= RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD
            and not cb["open"]
        ):
            cb["open"] = True
            cb["tripped"] = True
            logger.warning(
                "RiskScore LLM circuit opened after %d consecutive failures — "
                "applying fail-safe default to remaining validated findings for this run",
                cb["consecutive_failures"],
            )
    else:
        cb["consecutive_failures"] = 0


def _clause_type_value(raw) -> Optional[str]:
    """Normalize clause_type to its string value for the scoring prompt.

    Accepts: ClauseType enum, str, or None. Returns Optional[str].
    Identical to Node 4's helper (self_rag_validation_agent.py:355-364).
    """
    if isinstance(raw, ClauseType):
        return raw.value
    if isinstance(raw, str):
        return raw
    return None
