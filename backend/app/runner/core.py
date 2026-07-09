"""
Pipeline runner core — entry-agnostic orchestration.

Spike result: stream_mode="values" chosen. Each yield is the full ContractState
after the node completes; reading state["current_node"] gives node identity with
no accumulation needed. Confirmed via fake-graph unit tests (Tasks 8/9).

Called by both the API background worker (app.runner.worker) and the CLI
(app.runner.__main__). No LLM calls made here; per-node timeouts live in the nodes.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from app.graph.builder import build_graph
from app.delivery import deliver_report_sync
from app.runner.progress import node_index, TOTAL_STAGES

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NodeProgress:
    node: str
    index: Optional[int]
    total: int
    elapsed_seconds: Optional[float]


@dataclass
class RunResult:
    final_state: dict
    report_path: Optional[str]
    mcp_delivery_status: dict
    ingest_error: Optional[dict]


def run_pipeline(
    document_path: str,
    *,
    recipient: Optional[str] = None,
    on_progress: Optional[Callable[[NodeProgress], None]] = None,
) -> RunResult:
    """Run the full pipeline graph for a contract document.

    Seeds only document_path and processing_started_at (spec AC-3/6).
    Streams values mode; fires on_progress once per distinct node.
    Calls deliver_report_sync after the graph terminates.
    Stamps processing_completed_at on the final state before returning.
    """
    initial = {
        "document_path": document_path,
        "processing_started_at": _now_iso(),
    }

    graph = build_graph()
    final_state: dict = {}
    last_node: Optional[str] = None

    for state in graph.stream(initial, stream_mode="values"):
        final_state = state
        node = state.get("current_node")
        if node and node != last_node:
            last_node = node
            if on_progress is not None:
                # Per-node elapsed time is written by each node as
                # node_timings={current_node: elapsed} (spec §2.4); read it here so
                # SSE can surface elapsed_seconds. None when the node did not record one.
                timing = (state.get("node_timings") or {}).get(node)
                on_progress(
                    NodeProgress(
                        node=node,
                        index=node_index(node),
                        total=TOTAL_STAGES,
                        elapsed_seconds=timing,
                    )
                )

    delivery_result = deliver_report_sync(final_state, recipient=recipient)
    mcp_delivery_status = delivery_result.get("mcp_delivery_status", {})

    final_state["processing_completed_at"] = _now_iso()

    return RunResult(
        final_state=final_state,
        report_path=final_state.get("report_path"),
        mcp_delivery_status=mcp_delivery_status,
        ingest_error=final_state.get("ingest_error"),
    )
