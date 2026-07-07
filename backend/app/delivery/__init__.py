"""
app.delivery — MCP delivery step (post-terminal transport layer).

Delivers the report ReportAgent (Node 7) wrote to disk over Google Drive
and Gmail. This is NOT a graph node (spec §8a D1); the graph remains
fixed at 7 nodes / 2 conditional edges ending at report → END.

Public API:
    deliver_report(state, *, recipient=None) -> dict  [async]
    deliver_report_sync(state, *, recipient=None) -> dict
"""

from app.delivery.delivery_step import deliver_report, deliver_report_sync

__all__ = ["deliver_report", "deliver_report_sync"]
