"""
Regex-based clause boundary detector for ClauseSplitterAgent (step 1 of 3).

No LLM dependency — independently testable. Windows line-ending safe.
"""

import re

import app.config as _config  # import module, not names, to allow monkeypatching in tests
from app.graph.nodes.splitters import ClauseBoundary

# Re-exposed as a bare module-level name so tests can monkeypatch it (feature 045). Read at CALL time
# inside split_by_regex — do not capture it in a default arg.
CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS = _config.CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS

# Spelled-out clause ordinals (feature 040) — a fixed English linguistic vocabulary (NOT a tunable
# threshold, so per constitution §3 it stays inline like the recital-keyword list below). Longer
# forms precede the bare cardinals they contain as a prefix so the trailing \b never truncates
# (e.g. "twentieth" before "twenty"). Covers cardinals ONE–TWENTY and ordinals FIRST–TWENTIETH.
_ORDINAL_WORDS = (
    "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    "eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
    "eighteenth|nineteenth|twentieth|"
    "eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    "one|two|three|four|five|six|seven|eight|nine|ten"
)

# Each pattern is compiled separately (inline flags like (?mi) must be at
# the start of each sub-expression — joining them with | breaks that).
_COMPILED_PATTERNS = [
    re.compile(r"(?m)^[ \t]*(\d+(?:\.\d+)*)\.?\s"),  # "1.", "1.1"
    re.compile(r"(?mi)^[ \t]*(article\s+\d+)"),  # "Article N"
    re.compile(r"(?mi)^[ \t]*(section\s+\d+(?:\.\d+)*)"),  # "Section N"
    re.compile(r"(?m)^[ \t]*(§\s*\d+(?:\.\d+)*)"),  # "§N"
    re.compile(
        r"(?mi)^[ \t]*(WHEREAS|NOW\s+THEREFORE|IN\s+WITNESS\s+WHEREOF|RECITALS?|BACKGROUND)"
    ),
    # feature 040: "CLAUSE 1" / "CLAUSE 1.2" / "CLAUSE ONE" / "Clause First". CLAUSE had no prior
    # pattern; here it accepts a digit OR a spelled-out ordinal. \b blocks prose ("Clause headings").
    re.compile(rf"(?mi)^[ \t]*(clause\s+(?:\d+(?:\.\d+)*|(?:{_ORDINAL_WORDS})))\b"),
    # feature 040: spelled-out ARTICLE/SECTION — "ARTICLE ONE" / "SECTION FIRST". Digit forms of
    # article/section are already matched by the pre-existing patterns above (which win by order).
    re.compile(rf"(?mi)^[ \t]*((?:article|section)\s+(?:{_ORDINAL_WORDS}))\b"),
]

# Feature 045: enumerated sub-list markers. Applied ONLY when CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS is
# True. By default (False) they are omitted so "(a)"/"(ii)"/"a." sub-items stay attached to their
# governing clause (the higher-level markers above still bound clauses). See specs/045.
_SUBLIST_PATTERNS = (
    re.compile(r"(?m)^[ \t]*(\([a-z]+\)|\([ivxlcdm]+\))\s"),  # "(a)", "(ii)"
    re.compile(r"(?m)^[ \t]*([a-z])\.[ \t]"),  # "a.", "b."
)

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

    # Feature 045: sub-list markers ("(a)"/"a.") only split when the flag is on (default off keeps
    # enumerated sub-items with their governing clause). Read the flag at call time (monkeypatchable).
    patterns = list(_COMPILED_PATTERNS)
    if CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS:
        patterns = patterns + list(_SUBLIST_PATTERNS)

    # Collect all marker matches across all patterns, keyed by start position.
    # If multiple patterns match at the same position, the first one wins.
    marker_map: dict = {}
    for pattern in patterns:
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
