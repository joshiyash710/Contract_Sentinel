"""
Integration tests for the MCP delivery step (feature 010).

End-to-end without the graph and without live Google: drives the
client→handler→result contract using stubbed MCP client wrappers and
a real Node-7 terminal state produced by running report_agent.

Run: python -m pytest tests/integration/test_delivery_integration.py -v
"""

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import app.graph.nodes.report_agent as report_mod
from app.graph.builder import build_graph
from app.graph.state import RiskLevel, ValidationStatus
from app.models.report import ContractReport

# ── fixtures & helpers ────────────────────────────────────────────────────────


def _minimal_terminal_state(tmp_path: Path) -> dict:
    """Build a ContractState that report_agent can consume; report goes to tmp_path."""
    return {
        "document_id": "integ_doc",
        "original_filename": "contract.pdf",
        "document_path": "/tmp/contract.pdf",
        "uploaded_at": "2026-07-07T00:00:00+00:00",
        "extracted_text": "This is the contract text.",
        "ocr_used": False,
        "ocr_confidence": None,
        "ingest_error": None,
        "clauses": {
            "c1": {
                "clause_id": "c1",
                "position": 1,
                "section_number": "1",
                "clause_type": "liability",
                "extracted_text": "Liability limited to $1.",
                "validation_status": ValidationStatus.VALIDATED,
                "risk_level": RiskLevel.HIGH,
                "risk_rationale": "Very risky.",
                "suggested_rewrite": "Liability limited to $1M.",
                "retrieval_path": None,
                "confidence_score": 0.9,
                "evidence_snippets": [],
                "retry_count": 0,
            }
        },
        "current_node": "report",
        "node_timings": {},
        "error_count": 0,
        "processing_started_at": "2026-07-07T00:00:00+00:00",
        "processing_completed_at": None,
        "risk_level": RiskLevel.HIGH,
        "report_path": None,
        "mcp_delivery_status": {},
    }


@pytest.fixture
def terminal_state(tmp_path):
    """Run report_agent on a minimal state, capturing report_path in tmp_path."""
    state = _minimal_terminal_state(tmp_path)
    with patch.object(report_mod, "REPORT_OUTPUT_DIR", str(tmp_path)):
        updates = report_mod.report_agent(state)
    state.update(updates)
    assert state["report_path"] is not None, "report_agent must write report_path"
    return state


# ── tests ─────────────────────────────────────────────────────────────────────


async def test_deliver_after_report_terminal_state(terminal_state):
    """Stubs receive the real report file path; both channels return SUCCESS."""
    from app.delivery.delivery_step import deliver_report
    from app.delivery.models import DeliveryResult

    md_path = terminal_state["report_path"]
    drive_stub = AsyncMock(
        return_value=DeliveryResult(
            service="drive", ok=True, resource_ref="https://drive.google.com/x"
        )
    )
    gmail_stub = AsyncMock(
        return_value=DeliveryResult(service="gmail", ok=True, resource_ref="msg_001")
    )

    with (
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        result = await deliver_report(terminal_state, recipient="test@example.com")

    from app.graph.state import MCPDeliveryStatus

    status = result["mcp_delivery_status"]
    assert status["drive"]["status"] == MCPDeliveryStatus.SUCCESS
    assert status["gmail"]["status"] == MCPDeliveryStatus.SUCCESS

    # Stubs received the real file path in one of the Drive upload calls
    uploaded_paths = [c[0][0] for c in drive_stub.call_args_list]
    assert md_path in uploaded_paths


async def test_deliver_reads_real_report_json_summary(terminal_state):
    """Gmail subject counts match the Node-7-produced JSON sibling's summary."""
    from app.delivery.delivery_step import deliver_report
    from app.delivery.models import DeliveryResult

    json_path = Path(terminal_state["report_path"]).with_suffix(".json")
    assert json_path.exists(), "report_agent must write the JSON sibling"
    report = ContractReport.model_validate_json(json_path.read_text(encoding="utf-8"))

    gmail_stub = AsyncMock(return_value=DeliveryResult(service="gmail", ok=True))
    drive_stub = AsyncMock(return_value=DeliveryResult(service="drive", ok=True))

    with (
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        await deliver_report(terminal_state, recipient="test@example.com")

    subject = gmail_stub.call_args[0][1]
    # Subject should contain the validated_findings count from the real report
    assert str(report.summary.validated_findings) in subject


def test_delivery_does_not_touch_graph():
    """delivery_step does not import app.graph.builder; graph ends at report→END."""
    import app.delivery.delivery_step as delivery_step

    # Primary assertion: delivery_step source contains no graph builder import
    source = inspect.getsource(delivery_step)
    assert "app.graph.builder" not in source
    assert "build_graph" not in source

    # Secondary: graph structure unchanged — report's only successor is END
    graph = build_graph()
    compiled = graph.get_graph()
    report_edges = [e for e in compiled.edges if e[0] == "report"]
    # All edges from report must go to END (the terminal node is __end__)
    assert report_edges, "report node must have outgoing edges"
    for edge in report_edges:
        assert edge[1] == "__end__", f"Unexpected edge from report: {edge}"


async def test_delivery_step_state_key_only(terminal_state):
    """Partial dict has only mcp_delivery_status; merge_dicts reducer works correctly."""
    from app.delivery.delivery_step import deliver_report
    from app.delivery.models import DeliveryResult
    from app.graph.state import MCPDeliveryStatus, merge_dicts

    drive_stub = AsyncMock(return_value=DeliveryResult(service="drive", ok=True))
    gmail_stub = AsyncMock(return_value=DeliveryResult(service="gmail", ok=True))

    prior_status = {
        "drive": {
            "status": MCPDeliveryStatus.FAILED,
            "error_message": "old",
            "delivered_at": None,
        }
    }

    with (
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        partial = await deliver_report(terminal_state, recipient="test@example.com")

    assert set(partial.keys()) == {"mcp_delivery_status"}

    merged = merge_dicts(prior_status, partial["mcp_delivery_status"])
    assert set(merged.keys()) == {"drive", "gmail"}
    assert merged["drive"]["status"] == MCPDeliveryStatus.SUCCESS
