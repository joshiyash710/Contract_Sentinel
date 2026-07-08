"""
Node-name to pipeline-stage-index mapping for SSE progress reporting.

NODE_INDEX maps every graph node name to its 1-based stage index. The two
branching node names (redline / skip_redline) share index 6 because only one
fires per run. Stdlib only — no graph import.
"""

from typing import Optional

NODE_INDEX: dict = {
    "ingest_agent": 1,
    "clause_splitter": 2,
    "crag_retrieval": 3,
    "self_rag_validation": 4,
    "risk_score": 5,
    "redline": 6,
    "skip_redline": 6,
    "report": 7,
}

TOTAL_STAGES: int = 7


def node_index(node_name: str) -> Optional[int]:
    """Return the stage index for node_name, or None if unknown."""
    return NODE_INDEX.get(node_name)
