"""
Shared helpers for the Self-RAG validator modules.

format_evidence renders 001-shape evidence snippets into a single prompt-ready
block, truncated to a char budget. Placing it in the package __init__ (like
make_snippet in retrievers/__init__.py) keeps the "001 evidence shape" assumption
in one place for both reflectors.py and the node.
"""

from typing import List, Dict, Any, Optional


def format_evidence(snippets: Optional[List[Dict[str, Any]]], max_chars: int) -> str:
    """Render evidence snippets into a single prompt block, truncated to max_chars.

    Each snippet is the 001 shape {"snippet_text": str, "source_reference": str}.
    Returns "" when snippets is None or empty (the empty-evidence path formats its
    own "no evidence" wording in the reflector). Truncation is applied to the
    concatenated block so total prompt input is bounded (spec §4.9).
    """
    if not snippets:
        return ""
    parts = []
    for i, s in enumerate(snippets, start=1):
        text = (s.get("snippet_text") or "").strip()
        src = (s.get("source_reference") or "").strip()
        if text:
            parts.append(f"[{i}] ({src}) {text}")
    block = "\n".join(parts)
    return block[:max_chars]
