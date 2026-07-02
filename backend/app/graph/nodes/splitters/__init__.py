"""
Shared types for clause-splitter modules.

ClauseBoundary is the return element type for both
regex_splitter.split_by_regex() and llm_refiner.refine_with_llm().
Placing it in the package __init__ (like ParseResult in parsers/__init__.py)
lets regex_splitter.py and llm_refiner.py both import it without creating a
cross-dependency between the two modules.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ClauseBoundary:
    """A single detected clause boundary with its metadata.

    Attributes:
        clause_id: Stable positional key (e.g. "clause_001").
        text: The full text content of the clause.
        position: 1-indexed position in the document.
        section_number: Detected section number (e.g. "1.2", "Article 5"),
            or None if no section marker detected.
        clause_type: Raw string clause type before enum conversion
            (e.g. "definitions", "payment"), or None if not inferred.
    """

    clause_id: str
    text: str
    position: int
    section_number: Optional[str]
    clause_type: Optional[str]  # raw string before ClauseType enum conversion
