"""
Regex-based clause boundary detector for ClauseSplitterAgent (step 1 of 3).

No LLM dependency — independently testable. Windows line-ending safe.
"""

import re
from app.graph.nodes.splitters import ClauseBoundary

# Each pattern is compiled separately (inline flags like (?mi) must be at
# the start of each sub-expression — joining them with | breaks that).
_COMPILED_PATTERNS = [
    re.compile(r"(?m)^[ \t]*(\d+(?:\.\d+)*)\.?\s"),  # "1.", "1.1"
    re.compile(r"(?mi)^[ \t]*(article\s+\d+)"),  # "Article N"
    re.compile(r"(?mi)^[ \t]*(section\s+\d+(?:\.\d+)*)"),  # "Section N"
    re.compile(r"(?m)^[ \t]*(§\s*\d+(?:\.\d+)*)"),  # "§N"
    re.compile(r"(?m)^[ \t]*(\([a-z]+\)|\([ivxlcdm]+\))\s"),  # "(a)", "(ii)"
    re.compile(r"(?m)^[ \t]*([a-z])\.[ \t]"),  # "a.", "b."
    re.compile(
        r"(?mi)^[ \t]*(WHEREAS|NOW\s+THEREFORE|IN\s+WITNESS\s+WHEREOF|RECITALS?|BACKGROUND)"
    ),
]

_PARAGRAPH_PATTERN = re.compile(r"\n\s*\n")


def split_by_regex(text: str) -> list:
    """Split contract text into clauses using regex-detected structural markers.

    Returns:
        List of ClauseBoundary objects sorted by position.
        Returns [] for empty input.
        Returns at least 1 clause for non-empty input.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if not text.strip():
        return []

    # Collect all marker matches across all patterns, keyed by start position.
    # If multiple patterns match at the same position, the first one wins.
    marker_map: dict = {}
    for pattern in _COMPILED_PATTERNS:
        for match in pattern.finditer(text):
            pos = match.start()
            if pos not in marker_map:
                marker_map[pos] = match

    if marker_map:
        sorted_matches = [marker_map[k] for k in sorted(marker_map)]
        return _build_clauses_from_matches(text, sorted_matches)

    # Fallback 1: paragraph splitting
    para_splits = list(_PARAGRAPH_PATTERN.finditer(text))
    if para_splits:
        return _build_clauses_from_paragraph_splits(text, para_splits)

    # Fallback 2: entire text as one clause
    return [
        ClauseBoundary(
            clause_id="clause_001",
            text=text.strip(),
            position=1,
            section_number=None,
            clause_type=None,
        )
    ]


def _extract_section_number(match: re.Match) -> str:
    """Extract the section number string from the first non-None capture group."""
    for group in match.groups():
        if group is not None:
            return group.strip()
    return None


def _build_clauses_from_matches(text: str, matches: list) -> list:
    """Build clauses from structural marker match positions."""
    raw = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        clause_text = text[start:end].strip()
        if clause_text:
            raw.append((clause_text, _extract_section_number(match)))

    if not raw:
        return [
            ClauseBoundary(
                clause_id="clause_001",
                text=text.strip(),
                position=1,
                section_number=None,
                clause_type=None,
            )
        ]

    return [
        ClauseBoundary(
            clause_id=f"clause_{i:03d}",
            text=clause_text,
            position=i,
            section_number=section_number,
            clause_type=None,
        )
        for i, (clause_text, section_number) in enumerate(raw, start=1)
    ]


def _build_clauses_from_paragraph_splits(text: str, splits: list) -> list:
    """Build clauses from double-newline paragraph boundaries."""
    positions = [0] + [m.end() for m in splits] + [len(text)]
    clauses = []
    position = 1
    for i in range(len(positions) - 1):
        chunk = text[positions[i] : positions[i + 1]].strip()
        if chunk:
            clauses.append(
                ClauseBoundary(
                    clause_id=f"clause_{position:03d}",
                    text=chunk,
                    position=position,
                    section_number=None,
                    clause_type=None,
                )
            )
            position += 1

    if not clauses:
        return [
            ClauseBoundary(
                clause_id="clause_001",
                text=text.strip(),
                position=1,
                section_number=None,
                clause_type=None,
            )
        ]
    return clauses
