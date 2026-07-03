"""
Shared types for CRAG retriever modules.

RetrievalResult is the return type for both kb_retriever.search_kb() and
web_retriever.web_search(). make_snippet() builds an evidence dict in the exact
001-schema shape. Placing them in the package __init__ (like ClauseBoundary in
splitters/__init__.py) lets kb_retriever.py and web_retriever.py both import
them without a cross-dependency.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class RetrievalResult:
    """Outcome of one retriever call for a single clause.

    Attributes:
        snippets: Evidence snippets, each a dict with EXACTLY the keys
            {"snippet_text": str, "source_reference": str} (001-schema §3).
            Empty list = "path executed but found nothing".
        top_score: Top-1 cosine for the local-KB path (in [0.0, 1.0]);
            None for the web path (which has no score).
    """

    snippets: List[Dict[str, Any]]
    top_score: Optional[float]


def make_snippet(snippet_text: str, source_reference: str) -> Dict[str, str]:
    """Build an evidence snippet in the exact 001 shape (only the two reserved
    keys), so AC-6 holds regardless of source path."""
    return {"snippet_text": snippet_text, "source_reference": source_reference}
