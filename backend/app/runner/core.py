"""
Pipeline runner core — entry-agnostic orchestration.

Spike result: stream_mode="values" chosen. Each yield is the full ContractState
after the node completes; reading state["current_node"] gives node identity with
no accumulation needed. Confirmed via fake-graph unit tests (Tasks 8/9).

Called by both the API background worker (app.runner.worker) and the CLI
(app.runner.__main__). No LLM calls made here; per-node timeouts live in the nodes.

Feature 012 additions:
- checkpointer / thread_id / resume / already_completed params for durable runs.
- seen-set dedup on already_completed prevents re-emitting progress for nodes that
  stream(None) re-emits as its first yield (spec EC-1).
- config passed to graph.stream when checkpointer is set (spec AC-10).
- Default (checkpointer=None) is byte-identical to 011 behaviour (spec D7).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

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
    checkpointer=None,
    thread_id: Optional[str] = None,
    resume: bool = False,
    already_completed: Optional[List[str]] = None,
) -> RunResult:
    """Run the full pipeline graph for a contract document.

    checkpointer / thread_id / resume / already_completed are the 012 additions.
    Default (checkpointer=None) is byte-identical to 011 behaviour (spec D7):
    config=None, fresh initial dict, no dedup overhead on a clean seen-set.

    resume=True streams None so LangGraph resumes from the last checkpoint (AC-11).
    already_completed seeds the dedup set so re-emitted nodes are not double-fired
    (spec EC-1 — stream(None) re-emits the last checkpointed node as its first yield).
    """
    config = {"configurable": {"thread_id": thread_id}} if checkpointer else None
    graph = build_graph(checkpointer=checkpointer)

    if resume:
        stream_input = None
    else:
        stream_input = {
            "document_path": document_path,
            "processing_started_at": _now_iso(),
        }

    seen = set(already_completed or ())
    final_state: dict = {}
    last_node: Optional[str] = None

    for state in graph.stream(stream_input, stream_mode="values", config=config):
        final_state = state
        node = state.get("current_node")
        if node and node != last_node and node not in seen:
            last_node = node
            seen.add(node)
            if on_progress is not None:
                timing = (state.get("node_timings") or {}).get(node)
                on_progress(
                    NodeProgress(
                        node=node,
                        index=node_index(node),
                        total=TOTAL_STAGES,
                        elapsed_seconds=timing,
                    )
                )
        else:
            last_node = node

    delivery_result = deliver_report_sync(final_state, recipient=recipient)
    mcp_delivery_status = delivery_result.get("mcp_delivery_status", {})

    final_state["processing_completed_at"] = _now_iso()

    return RunResult(
        final_state=final_state,
        report_path=final_state.get("report_path"),
        mcp_delivery_status=mcp_delivery_status,
        ingest_error=final_state.get("ingest_error"),
    )
