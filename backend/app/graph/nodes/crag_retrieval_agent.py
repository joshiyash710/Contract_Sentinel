"""
CRAG Retrieval Agent — Node 3 of the ContractSentinel LangGraph pipeline.

Responsibility: for each clause produced by ClauseSplitterAgent, gather
supporting evidence by routing through either the local FAISS clause KB
(high confidence) or a live DuckDuckGo web search (low confidence).

Constitution rules observed:
  §3  — all thresholds sourced from app.config (re-exposed as module-level names
          for monkeypatching in tests — same pattern as clause_splitter_agent.py)
  §5  — returns only the state keys this node owns (partial-update rule)
  §7  — implementation follows TDD cycle defined in tasks.md
  §8  — embedding uses OLLAMA_EMBED_MODEL_NAME (bge-m3), distinct from
          OLLAMA_MODEL_NAME (generative Qwen3)

Constitution §2 interpretation (spec §7.2 — required to be documented here):
  CRAG's "confidence-based routing" is one of the two permitted conditional
  edges, but it is realized as INTERNAL Python branching inside this node,
  NOT as a graph-level add_conditional_edges. The reason: a graph-level
  conditional edge routes the whole ContractState to one successor, but CRAG
  routes PER CLAUSE, and all clauses live in one state object held by one node.
  A Send-API map-reduce subgraph was rejected for Phase 1 as unnecessary
  complexity (spec §7.2). builder.py adds a plain linear add_edge.

Reads from state:
    clauses, document_id, ingest_error

Writes to state (partial dict):
    clauses (per-clause evidence updates), current_node, node_timings

Does NOT write:
    document_id, extracted_text, ocr_used, ingest_error, report_path,
    evidence_trail, mcp_delivery_status, error_count, retry_budgets
"""

import logging
import time

import app.config as _config

from app.graph.state import ContractState, RetrievalPath
from app.graph.nodes.retrievers.embeddings import embed_query
from app.graph.nodes.retrievers.kb_retriever import load_kb, search_kb
from app.graph.nodes.retrievers.web_retriever import web_search

logger = logging.getLogger("contractsentinel.crag_retrieval")

# Re-expose as module-level names so tests can monkeypatch them:
#   monkeypatch.setattr(crag_mod, "CRAG_CONFIDENCE_THRESHOLD", 0.5)
OLLAMA_EMBED_MODEL_NAME = _config.OLLAMA_EMBED_MODEL_NAME
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME  # re-exposed for AC-8 comparison in tests
CRAG_CONFIDENCE_THRESHOLD = _config.CRAG_CONFIDENCE_THRESHOLD
CRAG_TOP_K = _config.CRAG_TOP_K
CRAG_WEB_MAX_RESULTS = _config.CRAG_WEB_MAX_RESULTS
CRAG_MAX_EVIDENCE_SNIPPETS = _config.CRAG_MAX_EVIDENCE_SNIPPETS
CRAG_QUERY_MAX_CHARS = _config.CRAG_QUERY_MAX_CHARS
CRAG_EMBED_TIMEOUT_SECONDS = _config.CRAG_EMBED_TIMEOUT_SECONDS
CRAG_WEB_TIMEOUT_SECONDS = _config.CRAG_WEB_TIMEOUT_SECONDS
CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD = _config.CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD


def crag_retrieval_agent(state: ContractState) -> dict:
    """LangGraph Node 3. Reads clauses/document_id/ingest_error; returns partial
    dict: clauses (per-clause evidence updates), current_node, node_timings."""
    start_time = time.monotonic()
    current_node = "crag_retrieval"
    document_id = state.get("document_id", "unknown")

    # ── Defensive: skip if IngestAgent reported an error (AC-10) ─────────────
    if state.get("ingest_error") is not None:
        elapsed = time.monotonic() - start_time
        return {
            "clauses": {},
            "current_node": current_node,
            "node_timings": {current_node: elapsed},
        }

    clauses = state.get("clauses", {})

    # ── Guard: empty clauses dict (AC-11) ────────────────────────────────────
    if not clauses:
        logger.warning(
            "CRAGRetrievalAgent: empty clauses dict for document_id=%s", document_id
        )
        elapsed = time.monotonic() - start_time
        return {
            "clauses": {},
            "current_node": current_node,
            "node_timings": {current_node: elapsed},
        }

    # ── Load KB once (None if unavailable — AC-14 warning is inside load_kb) ─
    kb = load_kb()

    # ── Circuit-breaker state (spec §4.13 / AC-16) ───────────────────────────
    consecutive_failures = 0
    circuit_open = False

    clause_updates: dict = {}

    # Process in document order (by position)
    ordered = sorted(clauses.items(), key=lambda kv: kv[1].get("position", 0))

    for clause_id, record in ordered:
        # ── a. Empty-text guard (spec §4.3) ──────────────────────────────────
        text = (record.get("text") or "").strip()
        if not text:
            logger.warning(
                "CRAGRetrievalAgent: empty clause text for clause_id=%s document_id=%s",
                clause_id,
                document_id,
            )
            clause_updates[clause_id] = {
                "confidence_score": None,
                "path_taken": None,
                "evidence_snippets": None,
            }
            continue

        # ── b. Truncate query (spec §4.11) ───────────────────────────────────
        query = text[:CRAG_QUERY_MAX_CHARS]
        if len(text) > CRAG_QUERY_MAX_CHARS:
            logger.debug(
                "CRAGRetrievalAgent: clause_id=%s text truncated from %d to %d chars",
                clause_id,
                len(text),
                CRAG_QUERY_MAX_CHARS,
            )

        # ── c. Embed (skip if circuit open) ──────────────────────────────────
        kb_result = None  # initialize up front to avoid UnboundLocalError
        query_vec = None

        if not circuit_open:
            embed_start = time.monotonic()
            query_vec = embed_query(
                query, CRAG_EMBED_TIMEOUT_SECONDS, OLLAMA_EMBED_MODEL_NAME
            )
            embed_latency = time.monotonic() - embed_start

            if query_vec is None:
                consecutive_failures += 1
                if consecutive_failures >= CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD:
                    circuit_open = True
                    logger.warning(
                        "CRAGRetrievalAgent: embedding circuit breaker OPENED after %d "
                        "consecutive failures — remaining clauses route directly to web "
                        "(document_id=%s)",
                        consecutive_failures,
                        document_id,
                    )
            else:
                consecutive_failures = 0  # reset on success

        # ── d. Decide confidence + path (None-vs-0.0 rule from plan §2) ─────
        if kb is None:
            # KB unavailable: confidence 0.0 if we have a vector, else None
            confidence = 0.0 if query_vec is not None else None
            path = RetrievalPath.WEB_FALLBACK
        elif query_vec is None:
            # Could not embed (embed failure or circuit open)
            confidence = None
            path = RetrievalPath.WEB_FALLBACK
        else:
            kb_result = search_kb(kb, query_vec, CRAG_TOP_K)
            confidence = kb_result.top_score  # max(0.0, top-1 cosine)
            if confidence >= CRAG_CONFIDENCE_THRESHOLD:  # inclusive >= (AC-4)
                path = RetrievalPath.LOCAL_KB
            else:
                path = RetrievalPath.WEB_FALLBACK

        # ── e. Gather evidence for the chosen path ────────────────────────────
        web_latency = None
        if path == RetrievalPath.LOCAL_KB:
            snippets = kb_result.snippets
        else:
            web_start = time.monotonic()
            web_result = web_search(
                query, CRAG_WEB_MAX_RESULTS, CRAG_WEB_TIMEOUT_SECONDS
            )
            web_latency = time.monotonic() - web_start
            snippets = web_result.snippets  # [] on any failure — never raises

        # ── f. Cap snippets (AC-7) ────────────────────────────────────────────
        snippets = snippets[:CRAG_MAX_EVIDENCE_SNIPPETS]

        # ── g. Stage per-clause update (only the three evidence fields) ───────
        clause_updates[clause_id] = {
            "confidence_score": confidence,
            "path_taken": path,
            "evidence_snippets": snippets,
        }

        # ── h. Per-clause structured log (spec §8 — logs only, NOT state) ─────
        logger.info(
            "CRAGRetrievalAgent: clause processed",
            extra={
                "clause_id": clause_id,
                "document_id": document_id,
                "confidence_score": confidence,
                "path_taken": path.value if path is not None else None,
                "snippet_count": len(snippets),
                "embed_latency_seconds": (
                    round(embed_latency, 4)
                    if not circuit_open and query_vec is not None
                    else None
                ),
                "web_latency_seconds": (
                    round(web_latency, 4) if web_latency is not None else None
                ),
            },
        )

    elapsed = time.monotonic() - start_time

    logger.info(
        "CRAGRetrievalAgent completed",
        extra={
            "document_id": document_id,
            "clause_count": len(clause_updates),
            "elapsed_seconds": round(elapsed, 4),
        },
    )

    # ── Return: ONLY the three keys (AC-12 — no error_count) ─────────────────
    return {
        "clauses": clause_updates,
        "current_node": current_node,
        "node_timings": {current_node: elapsed},
    }
