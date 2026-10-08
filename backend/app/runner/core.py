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

import app.config as _config
from app.graph.builder import build_graph
from app.delivery import deliver_report_sync
from app.graph.state import ValidationStatus
from app.runner.progress import node_index, TOTAL_STAGES

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enum_value(raw):
    """Return raw.value for an Enum, raw unchanged for a str/None. Mirrors report_assembler._enum_value;
    inlined because the runner must not import graph-node modules (runner-isolation guard, spec §1)."""
    from enum import Enum

    if isinstance(raw, Enum):
        return raw.value
    return raw


def _validated_finding_items(final_state: dict) -> List[dict]:
    """Feature 061: this run's VALIDATED-finding clauses, as per-user-KB items.

    Uses the SAME validated predicate report_assembler uses — `final_status == ValidationStatus.VALIDATED`
    (ValidationStatus is a str-enum, so a checkpoint-round-tripped plain string compares equal). risk_level
    is normalized via report_assembler._enum_value so an enum or a str both render. Kept in lockstep with
    report_assembler.py so the two selections cannot drift.
    """
    doc_ref = final_state.get("original_filename") or final_state.get("document_id") or "contract"
    items: List[dict] = []
    for record in (final_state.get("clauses") or {}).values():
        if record.get("final_status") != ValidationStatus.VALIDATED:
            continue
        text = (record.get("text") or "").strip()
        if not text:
            continue
        risk = _enum_value(record.get("risk_level")) or "unspecified"
        items.append({"text": text, "source_reference": f"Your contract: {doc_ref} — {risk} risk"})
    return items


def _maybe_write_user_kb(final_state: dict, user_id: Optional[str]) -> None:
    """Feature 061: best-effort append of this run's VALIDATED findings to the uploading user's private KB.

    Self-gated (flag + user_id + non-empty items). NEVER raises into the run — the analysis and report have
    already succeeded; the learned-KB update is a best-effort side-effect (constitution §9)."""
    if not _config.CRAG_USER_KB_ENABLED or not user_id:
        return
    try:
        items = _validated_finding_items(final_state)
        if not items:
            return
        from app.rag import user_kb

        user_kb.append_clauses(user_id, items)
    except Exception:  # noqa: BLE001 — best-effort; a KB-write failure must not break the run
        logger.warning("user-KB append failed (best-effort, run unaffected)", exc_info=True)


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
    original_filename: Optional[str] = None,
    on_progress: Optional[Callable[[NodeProgress], None]] = None,
    checkpointer=None,
    thread_id: Optional[str] = None,
    resume: bool = False,
    already_completed: Optional[List[str]] = None,
    drive_token_json: Optional[str] = None,
    on_clause: Optional[Callable[[dict], None]] = None,
    user_id: Optional[str] = None,
) -> RunResult:
    """Run the full pipeline graph for a contract document.

    checkpointer / thread_id / resume / already_completed are the 012 additions.
    Default (checkpointer=None) is byte-identical to 011 behaviour (spec D7):
    config=None, fresh initial dict, no dedup overhead on a clean seen-set.

    resume=True streams None so LangGraph resumes from the last checkpoint (AC-11).
    already_completed seeds the dedup set so re-emitted nodes are not double-fired
    (spec EC-1 — stream(None) re-emits the last checkpointed node as its first yield).
    """
    # Feature 061: forward user_id on the config channel (NOT ContractState) so CRAG can augment with the
    # user's KB. Only built when checkpointer is set — the no-checkpointer CLI path stays config=None
    # (byte-identical streaming), so CRAG resolves user_id=None there (EC-2/AC-6).
    configurable = {"thread_id": thread_id}
    if user_id is not None:
        configurable["user_id"] = user_id
    config = {"configurable": configurable} if checkpointer else None
    graph = build_graph(checkpointer=checkpointer)

    if resume:
        stream_input = None
    else:
        stream_input = {
            "document_path": document_path,
            "processing_started_at": _now_iso(),
        }
        # Seed the real uploaded name so ingest_agent uses it (feature 018). Only when
        # provided → keeps the 011/012 default byte-identical.
        if original_filename is not None:
            stream_input["original_filename"] = original_filename

    seen = set(already_completed or ())
    final_state: dict = {}
    last_node: Optional[str] = None

    # Feature 059: when an on_clause callback is provided, also request the "custom" stream so CRAG's
    # per-clause progress payloads are forwarded. Each yield is then a (mode, chunk) tuple. Without a
    # callback the stream stays single-mode "values" (plain-state yields) — byte-identical to pre-059.
    live = on_clause is not None
    stream_mode = ["values", "custom"] if live else "values"

    for item in graph.stream(stream_input, stream_mode=stream_mode, config=config):
        if live:
            mode, chunk = item
            if mode == "custom":
                on_clause(chunk)  # separate branch — never touches the node seen/last_node dedup (AC-4)
                continue
            state = chunk
        else:
            state = item
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

    delivery_result = deliver_report_sync(
        final_state, recipient=recipient, drive_token_json=drive_token_json
    )
    mcp_delivery_status = delivery_result.get("mcp_delivery_status", {})

    final_state["processing_completed_at"] = _now_iso()

    # Feature 061: grow the uploading user's private learned KB from this run's validated findings.
    _maybe_write_user_kb(final_state, user_id)

    return RunResult(
        final_state=final_state,
        report_path=final_state.get("report_path"),
        mcp_delivery_status=mcp_delivery_status,
        ingest_error=final_state.get("ingest_error"),
    )
