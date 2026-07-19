"""
Self-RAG Validation Agent — Node 4 of the ContractSentinel LangGraph pipeline.

Responsibility: run three reflective LLM judgments per clause (Relevance → ISREL →
ISSUP) against CRAG-produced evidence to decide whether each clause is a finding
worth surfacing (VALIDATED) or can be discarded (DISCARDED).

Constitution rules observed:
  §3  — all thresholds sourced from app.config (re-exposed as module-level names
          for monkeypatching in tests — same pattern as clause_splitter_agent.py)
  §5  — partial-update rule: returns only clauses, current_node, node_timings,
          plus error_count:1 in the one case the circuit breaker opens (§8a R5)
  §7  — implementation follows TDD cycle defined in tasks.md
  §8  — every LLM call uses OLLAMA_MODEL_NAME (generative); never OLLAMA_EMBED_MODEL_NAME

Reads from state:
    clauses, document_id, ingest_error

Writes to state (partial dict):
    clauses (per-clause verdict fields), current_node, node_timings
    + error_count:1 IFF the circuit breaker opened this run

Does NOT write:
    document_id, extracted_text, ocr_used, ingest_error, report_path,
    evidence_trail, mcp_delivery_status, retry_budgets (except error_count on breach)
"""

import logging
import time
from typing import Optional

import app.config as _config

from app.graph.state import ContractState, ClauseType, ValidationStatus
from app.graph.nodes.validators.reflectors import (
    check_relevance,
    check_isrel,
    check_issup,
)

logger = logging.getLogger("contractsentinel.self_rag_validation")

# Re-expose as module-level names so tests can monkeypatch them.
# Read by bare name in node logic — never via _config.NAME — so monkeypatching works.
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
SELF_RAG_MAX_ATTEMPTS = _config.SELF_RAG_MAX_ATTEMPTS
SELF_RAG_TIMEOUT_SECONDS = _config.SELF_RAG_TIMEOUT_SECONDS
SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD = _config.SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD
SELF_RAG_PROMPT_MAX_CHARS = _config.SELF_RAG_PROMPT_MAX_CHARS
SELF_RAG_HIGH_RISK_CLAUSE_TYPES = _config.SELF_RAG_HIGH_RISK_CLAUSE_TYPES
SELF_RAG_RECALL_FLOOR_TYPES = _config.SELF_RAG_RECALL_FLOOR_TYPES  # spec 027; supersedes high-risk in-node


def self_rag_validation_agent(state: ContractState) -> dict:
    """LangGraph Node 4. Reads clauses/document_id/ingest_error; returns partial
    dict: clauses (per-clause verdict updates), current_node, node_timings, and
    error_count:1 ONLY when the circuit breaker opened."""
    start_time = time.monotonic()
    current_node = "self_rag_validation"
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
            "SelfRAGValidationAgent: no clauses to validate for document_id=%s",
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

    for clause_id, record in sorted_clauses:
        verdict = _process_clause(clause_id, record, cb, document_id)
        clause_updates[clause_id] = verdict

        logger.info(
            "SelfRAG clause verdict",
            extra={
                "document_id": document_id,
                "clause_id": clause_id,
                "relevance_verdict": verdict["relevance_verdict"],
                "isrel_verdict": verdict["isrel_verdict"],
                "issup_verdict": verdict["issup_verdict"],
                "retry_count": verdict["retry_count"],
                "final_status": (
                    verdict["final_status"].value if verdict["final_status"] else None
                ),
                "circuit_open": cb["open"],
            },
        )

    elapsed = time.monotonic() - start_time

    # Log aggregate metrics (spec §9)
    validated_count = sum(
        1
        for v in clause_updates.values()
        if v["final_status"] == ValidationStatus.VALIDATED
    )
    logger.info(
        "SelfRAGValidationAgent completed",
        extra={
            "document_id": document_id,
            "total_clauses": len(clause_updates),
            "validated": validated_count,
            "discarded": len(clause_updates) - validated_count,
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
        out["error_count"] = 1  # health signal — at most once per run (§8a R5)
    return out


def _process_clause(clause_id: str, record: dict, cb: dict, document_id: str) -> dict:
    """Compute the five verdict fields for one clause. Mutates cb in place."""
    text = (record.get("text") or "").strip()

    # ── Edge Case 6: empty / whitespace text → zero-LLM discard ──────────────
    if not text:
        logger.warning(
            "SelfRAG: empty/whitespace clause text for clause_id=%s document_id=%s",
            clause_id,
            document_id,
        )
        return _all_none_discard()

    evidence = record.get("evidence_snippets")
    empty_evidence = evidence is None or len(evidence) == 0
    ct = _clause_type_value(record.get("clause_type"))

    if empty_evidence:
        if ct in SELF_RAG_RECALL_FLOOR_TYPES:
            return _branch_a_rescue(text, ct, cb)
        else:
            # Branch B: zero-LLM discard — exempt from fail-open even after circuit trip
            return _all_none_discard()
    else:
        return _branch_c_normal(text, evidence, cb, ct)


def _branch_a_rescue(text: str, ct: Optional[str], cb: dict) -> dict:
    """Branch A: empty evidence, high-risk clause type.
    isrel_verdict = None (not-assessable). Run Relevance, then ISSUP on text alone."""
    if cb["open"]:
        # Circuit already open — apply fail-open (can't run rescue LLM calls)
        return {
            "relevance_verdict": None,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.VALIDATED,
        }

    relevance = check_relevance(
        text, SELF_RAG_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME, SELF_RAG_PROMPT_MAX_CHARS
    )
    _account(relevance, cb)

    if relevance is None:
        return {
            "relevance_verdict": None,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.VALIDATED,  # fail-open
        }
    if relevance is False:
        return {
            "relevance_verdict": False,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.DISCARDED,
        }

    # Recall floor (spec 027): a floor clause_type that is on-topic (relevance True)
    # is VALIDATED without the text-only ISSUP gate — a missed high-risk clause is
    # costlier than a false flag. Rescues the empty-evidence confidentiality/IP
    # ISSUP-false misses. (Empty/narrowed floor set falls through to _issup_loop.)
    if ct in SELF_RAG_RECALL_FLOOR_TYPES:
        return {
            "relevance_verdict": True,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.VALIDATED,
        }

    # relevance True → ISSUP on clause text alone (no evidence)
    issup_verdict, retry_count, final_status = _issup_loop(text, None, cb)
    return {
        "relevance_verdict": True,
        "isrel_verdict": None,  # not-assessable; absent evidence ≠ off-topic
        "issup_verdict": issup_verdict,
        "retry_count": retry_count,
        "final_status": final_status,
    }


def _branch_c_normal(text: str, evidence: list, cb: dict, ct: Optional[str] = None) -> dict:
    """Branch C: evidence present — run full Relevance → ISREL → ISSUP gate.
    For a recall-floor clause_type, relevance-True short-circuits to VALIDATED (spec 027)."""
    if cb["open"]:
        return {
            "relevance_verdict": None,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.VALIDATED,
        }

    relevance = check_relevance(
        text, SELF_RAG_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME, SELF_RAG_PROMPT_MAX_CHARS
    )
    _account(relevance, cb)

    if relevance is None:
        return {
            "relevance_verdict": None,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.VALIDATED,  # fail-open
        }
    if relevance is False:
        return {
            "relevance_verdict": False,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.DISCARDED,
        }

    # Recall floor (spec 027): an on-topic floor clause_type is VALIDATED without the
    # ISREL/ISSUP discard gates — rescues the liability/indemnification ISSUP-false and
    # termination ISREL-false misses (026), and skips 1-2 LLM calls per floor clause.
    if ct in SELF_RAG_RECALL_FLOOR_TYPES:
        return {
            "relevance_verdict": True,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.VALIDATED,
        }

    # Relevance True → ISREL check
    if cb["open"]:
        return {
            "relevance_verdict": True,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.VALIDATED,
        }

    isrel = check_isrel(
        text,
        evidence,
        SELF_RAG_TIMEOUT_SECONDS,
        OLLAMA_MODEL_NAME,
        SELF_RAG_PROMPT_MAX_CHARS,
    )
    _account(isrel, cb)

    if isrel is None:
        return {
            "relevance_verdict": True,
            "isrel_verdict": None,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.VALIDATED,  # fail-open
        }
    if isrel is False:
        return {
            "relevance_verdict": True,
            "isrel_verdict": False,
            "issup_verdict": None,
            "retry_count": None,
            "final_status": ValidationStatus.DISCARDED,
        }

    # Both pass → ISSUP loop
    issup_verdict, retry_count, final_status = _issup_loop(text, evidence, cb)
    return {
        "relevance_verdict": True,
        "isrel_verdict": True,
        "issup_verdict": issup_verdict,
        "retry_count": retry_count,
        "final_status": final_status,
    }


def _issup_loop(text: str, evidence: Optional[list], cb: dict):
    """Run ISSUP up to SELF_RAG_MAX_ATTEMPTS times. Returns (issup_verdict, retry_count, final_status).

    - LLM failure (None) short-circuits to fail-open immediately (no retry spin).
    - False retries until the cap; True returns early.
    - Exhaustion → DISCARDED with issup_verdict=False.
    """
    for attempt in range(1, SELF_RAG_MAX_ATTEMPTS + 1):
        if cb["open"]:
            # Circuit opened mid-loop — fail-open
            return (None, None, ValidationStatus.VALIDATED)

        issup = check_issup(
            text,
            evidence,
            SELF_RAG_TIMEOUT_SECONDS,
            OLLAMA_MODEL_NAME,
            SELF_RAG_PROMPT_MAX_CHARS,
        )
        _account(issup, cb)

        if issup is None:
            # LLM failure → fail-open immediately, do NOT retry
            return (None, None, ValidationStatus.VALIDATED)
        if issup is True:
            return (True, attempt - 1, ValidationStatus.VALIDATED)
        # issup is False → retry

    # All attempts exhausted with False
    return (False, SELF_RAG_MAX_ATTEMPTS - 1, ValidationStatus.DISCARDED)


def _account(verdict: Optional[bool], cb: dict) -> None:
    """Update circuit-breaker state after an LLM call result.

    None = LLM failure; any real verdict (True/False) resets the consecutive counter.
    When the threshold of consecutive failures is reached and the circuit isn't already
    open, opens it and sets tripped=True so the health signal is emitted once at return.
    """
    if verdict is None:
        cb["consecutive_failures"] += 1
        if (
            cb["consecutive_failures"] >= SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD
            and not cb["open"]
        ):
            cb["open"] = True
            cb["tripped"] = True
            logger.warning(
                "SelfRAG LLM circuit opened after %d consecutive failures — "
                "applying fail-open default to remaining clauses for this run",
                cb["consecutive_failures"],
            )
    else:
        cb["consecutive_failures"] = 0


def _clause_type_value(raw) -> Optional[str]:
    """Normalize clause_type to its string value for frozenset membership test.

    Accepts: ClauseType enum, str, or None. Returns Optional[str].
    """
    if isinstance(raw, ClauseType):
        return raw.value
    if isinstance(raw, str):
        return raw
    return None


def _all_none_discard() -> dict:
    """Return the zero-LLM discard verdict (empty text or non-high-risk empty evidence)."""
    return {
        "relevance_verdict": None,
        "isrel_verdict": None,
        "issup_verdict": None,
        "retry_count": None,
        "final_status": ValidationStatus.DISCARDED,
    }
