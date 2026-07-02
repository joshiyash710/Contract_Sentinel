"""
ClauseSplitterAgent — Node 2 of the ContractSentinel LangGraph pipeline.

Responsibility: segment extracted_text from IngestAgent into discrete clauses
and populate the clauses slice of ContractState.

Constitution rules observed:
  §3  — all thresholds sourced from app.config (re-exposed as module-level names
          for monkeypatching in tests — same pattern as ingest_agent.py)
  §5  — returns only the state keys this node owns (partial-update rule)
  §7  — implementation follows TDD cycle defined in tasks.md

Reads from state:
    extracted_text, document_id, ingest_error

Writes to state (partial dict):
    clauses, current_node, node_timings

Does NOT write:
    document_id, extracted_text, ocr_used, ingest_error, report_path,
    evidence_trail, mcp_delivery_status, error_count, retry_budgets
"""

import logging
import time
from typing import Optional

import app.config as _config  # import module, not names, to allow monkeypatching in tests

from app.graph.state import ContractState, ClauseType
from app.graph.nodes.splitters.regex_splitter import split_by_regex
from app.graph.nodes.splitters.llm_refiner import refine_with_llm
from app.graph.nodes.splitters import ClauseBoundary

logger = logging.getLogger("contractsentinel.clause_splitter")

# Re-expose as module-level names so tests can monkeypatch them:
#   monkeypatch.setattr(clause_splitter_agent_module, "MAX_CLAUSES_LIMIT", 2)
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
CLAUSE_SPLITTER_TIMEOUT_SECONDS = _config.CLAUSE_SPLITTER_TIMEOUT_SECONDS
MIN_CLAUSE_LENGTH = _config.MIN_CLAUSE_LENGTH
MAX_CLAUSES_LIMIT = _config.MAX_CLAUSES_LIMIT


def clause_splitter_agent(state: ContractState) -> dict:
    """LangGraph Node 2. Reads extracted_text/document_id/ingest_error;
    returns partial dict: clauses, current_node, node_timings."""
    start_time = time.monotonic()
    current_node = "clause_splitter"
    document_id = state.get("document_id", "unknown")

    # ── Defensive: skip if IngestAgent reported an error ──────────────────────
    if state.get("ingest_error") is not None:
        elapsed = time.monotonic() - start_time
        return {
            "clauses": {},
            "current_node": current_node,
            "node_timings": {current_node: elapsed},
        }

    extracted_text = state.get("extracted_text", "")

    # ── Guard: empty text ─────────────────────────────────────────────────────
    if not extracted_text:
        logger.warning(
            "ClauseSplitterAgent received empty extracted_text for document_id=%s",
            document_id,
        )
        elapsed = time.monotonic() - start_time
        return {
            "clauses": {},
            "current_node": current_node,
            "node_timings": {current_node: elapsed},
        }

    # ── Short-text path: single clause, skip regex pre-pass ──────────────────
    if len(extracted_text) < MIN_CLAUSE_LENGTH:
        regex_clauses = [
            ClauseBoundary(
                clause_id="clause_001",
                text=extracted_text,
                position=1,
                section_number=None,
                clause_type=None,
            )
        ]
        # Still run through LLM for clause_type inference
        refined = refine_with_llm(
            regex_clauses, CLAUSE_SPLITTER_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME
        )
        return _build_return(refined, start_time, current_node, llm_used=True)

    # ── Normal path ───────────────────────────────────────────────────────────
    regex_clauses = split_by_regex(extracted_text)

    # Pre-LLM cap: bound the prompt size
    if len(regex_clauses) > MAX_CLAUSES_LIMIT:
        logger.warning(
            "ClauseSplitterAgent: regex produced %d clauses (limit=%d), truncating before LLM call",
            len(regex_clauses),
            MAX_CLAUSES_LIMIT,
        )
        regex_clauses = regex_clauses[:MAX_CLAUSES_LIMIT]

    refined = refine_with_llm(
        regex_clauses, CLAUSE_SPLITTER_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME
    )

    # Post-refinement re-clamp: LLM may split run-ons beyond the limit
    if len(refined) > MAX_CLAUSES_LIMIT:
        logger.warning(
            "ClauseSplitterAgent: LLM produced %d clauses (limit=%d), re-clamping",
            len(refined),
            MAX_CLAUSES_LIMIT,
        )
        refined = refined[:MAX_CLAUSES_LIMIT]
        refined = _renumber(refined)

    llm_used = refined is not regex_clauses
    return _build_return(refined, start_time, current_node, llm_used=llm_used)


def _to_clause_type(raw: Optional[str]) -> Optional[ClauseType]:
    if raw is None:
        return None
    try:
        return ClauseType(raw)
    except ValueError:
        return None


def _renumber(clauses: list) -> list:
    """Re-assign clause_id and position sequentially after truncation."""
    renumbered = []
    for i, c in enumerate(clauses, start=1):
        renumbered.append(
            ClauseBoundary(
                clause_id=f"clause_{i:03d}",
                text=c.text,
                position=i,
                section_number=c.section_number,
                clause_type=c.clause_type,
            )
        )
    return renumbered


def _build_return(
    clauses: list, start_time: float, current_node: str, llm_used: bool
) -> dict:
    """Convert ClauseBoundary list to the partial-update return dict."""
    clauses_dict = {}
    type_counts: dict = {}

    for c in clauses:
        converted_type = _to_clause_type(c.clause_type)
        clauses_dict[c.clause_id] = {
            "text": c.text,
            "position": c.position,
            "section_number": c.section_number,
            "clause_type": converted_type,
        }
        type_key = converted_type.value if converted_type is not None else None
        type_counts[type_key] = type_counts.get(type_key, 0) + 1

    clause_count = len(clauses_dict)
    section_marker_rate = (
        sum(1 for c in clauses if c.section_number is not None) / clause_count
        if clause_count > 0
        else 0.0
    )
    elapsed = time.monotonic() - start_time

    logger.info(
        "ClauseSplitterAgent completed",
        extra={
            "clause_count": clause_count,
            "llm_used": llm_used,
            "llm_latency_seconds": None,  # tracked inside refine_with_llm; use elapsed as proxy
            "clause_types": type_counts,
            "section_marker_rate": round(section_marker_rate, 4),
            "elapsed_seconds": round(elapsed, 4),
        },
    )

    return {
        "clauses": clauses_dict,
        "current_node": current_node,
        "node_timings": {current_node: elapsed},
    }
