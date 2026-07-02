"""
Unit tests for app.graph.nodes.splitters.regex_splitter.split_by_regex().

No mocks, no Ollama, no network — pure regex logic only.
Written BEFORE the implementation (TDD red phase).

Run: python -m pytest tests/unit/test_regex_splitter.py -v
Expected before Task 5: FAIL (ImportError)
Expected after Task 5:  all 16 PASS
"""

import re

from app.graph.nodes.splitters import ClauseBoundary
from app.graph.nodes.splitters.regex_splitter import split_by_regex

# ── Shared assertion helper ────────────────────────────────────────────────────


def _assert_valid_boundaries(clauses: list) -> None:
    """Every clause must have non-empty text, valid position, and correct clause_id format."""
    for i, c in enumerate(clauses, start=1):
        assert isinstance(c, ClauseBoundary), f"Item {i} is not a ClauseBoundary"
        assert c.text.strip(), f"clause {c.clause_id} has empty text"
        assert isinstance(c.position, int), f"clause {c.clause_id} position not int"
        assert re.match(r"clause_\d{3}", c.clause_id), f"bad clause_id: {c.clause_id}"


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_split_numbered_sections():
    """Standard numbered contract produces one clause per numbered section."""
    text = (
        "1. Definitions\nThis section defines terms.\n"
        "2. Payment Terms\nPayment is due in 30 days.\n"
        "3. Termination\nEither party may terminate."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 3


def test_split_nested_numbers():
    """Nested numbering produces one clause per number."""
    text = (
        "1. General\nGeneral terms apply.\n"
        "1.1 Definitions\nTerms are defined here.\n"
        "1.2 Interpretation\nThe agreement shall be interpreted broadly.\n"
        "2. Payment\nPayment rules.\n"
        "2.1 Schedule\nPayment on the first of each month."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 5


def test_split_article_headers():
    """Article N headers produce correct boundaries."""
    text = (
        "Article 1 Definitions\nDefinitions go here.\n"
        "Article 2 Obligations\nObligations of both parties.\n"
        "Article 3 Termination\nTermination conditions."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 3


def test_split_section_headers():
    """Section N headers produce correct boundaries."""
    text = (
        "Section 1 Introduction\nThis agreement is made.\n"
        "Section 2 Scope\nScope of the agreement.\n"
        "Section 3.1 Sub-scope\nNested scope."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 3


def test_split_section_symbol():
    """§N markers produce correct boundaries."""
    text = (
        "§1 Definitions\nFirst section.\n"
        "§2 Payment\nSecond section.\n"
        "§3 Termination\nThird section."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 3


def test_split_lettered_sections():
    """(a), (b) lettered sections produce correct boundaries."""
    text = (
        "(a) First obligation\nThe first party shall.\n"
        "(b) Second obligation\nThe second party shall.\n"
        "(c) Third obligation\nThe third party shall."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 3


def test_split_contract_headers():
    """WHEREAS / NOW THEREFORE headers produce correct boundaries."""
    text = (
        "WHEREAS the parties wish to enter into this agreement;\n"
        "WHEREAS each party has the authority to sign;\n"
        "NOW THEREFORE in consideration of the mutual covenants herein."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) >= 2  # at least WHEREAS and NOW THEREFORE


def test_split_mixed_numbering():
    """Mixed numbering schemes do not crash and produce at least 2 clauses."""
    text = (
        "Article 1 Definitions\nDefinitions.\n"
        "Section 1.1 Terms\nSpecific terms.\n"
        "1.1.1 Sub-terms\nFurther detail.\n"
        "(a) First sub-item\nSub-item text."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) >= 2


def test_split_paragraph_fallback():
    """No structural markers → falls back to double-newline paragraph splitting."""
    text = (
        "This is the first paragraph of the agreement. It contains multiple sentences.\n\n"
        "This is the second paragraph with more details about the terms.\n\n"
        "This is the third paragraph describing the obligations."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 3
    # Paragraph-split clauses have no section_number
    for c in clauses:
        assert c.section_number is None


def test_split_single_block_fallback():
    """No markers and no double-newlines → entire text as one clause."""
    text = (
        "This is a single block of text with no paragraph breaks or markers whatsoever."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 1
    assert clauses[0].position == 1
    assert clauses[0].clause_id == "clause_001"


def test_split_empty_text():
    """Empty string → empty list."""
    clauses = split_by_regex("")
    assert clauses == []


def test_split_clause_ids_positional():
    """Clause IDs are 'clause_001', 'clause_002', ... zero-padded to 3 digits."""
    text = (
        "1. First clause text here.\n"
        "2. Second clause text here.\n"
        "3. Third clause text here."
    )
    clauses = split_by_regex(text)
    assert len(clauses) == 3
    assert clauses[0].clause_id == "clause_001"
    assert clauses[1].clause_id == "clause_002"
    assert clauses[2].clause_id == "clause_003"


def test_split_position_1_indexed():
    """Positions are 1, 2, 3, ... contiguous with no gaps."""
    text = (
        "1. First clause.\n"
        "2. Second clause.\n"
        "3. Third clause.\n"
        "4. Fourth clause."
    )
    clauses = split_by_regex(text)
    positions = [c.position for c in clauses]
    assert positions == list(range(1, len(clauses) + 1))


def test_split_section_number_extracted():
    """section_number is correctly extracted from matched markers."""
    text = (
        "1.2 Payment Terms\nPayment is due.\n"
        "Article 5 Obligations\nObligations here.\n"
        "Section 3.1 Definitions\nAll terms defined.\n"
        "§2 Confidentiality\nConfidential information.\n"
        "WHEREAS the parties agree.\n"
        "(a) First item of the list."
    )
    clauses = split_by_regex(text)
    section_numbers = [c.section_number for c in clauses]
    # Each clause should have a section_number (not None) since all have markers
    assert all(
        sn is not None for sn in section_numbers
    ), f"Expected all non-None section_numbers, got: {section_numbers}"
    # At least some of the expected values should appear
    combined = " ".join(str(sn) for sn in section_numbers)
    assert any(
        x in combined
        for x in ["1.2", "Article 5", "Section 3.1", "§2", "WHEREAS", "(a)"]
    )


def test_split_clause_type_always_none():
    """clause_type is always None from the regex pre-pass (no LLM involved)."""
    text = (
        "1. Definitions\nTerms are defined.\n" "2. Payment\nPayment is due in 30 days."
    )
    clauses = split_by_regex(text)
    for c in clauses:
        assert c.clause_type is None, f"Expected None clause_type, got {c.clause_type}"


def test_split_deterministic():
    """Same input produces identical output on two consecutive calls."""
    text = (
        "1. Definitions\nTerms.\n"
        "2. Payment\nPayment due.\n"
        "3. Termination\nTermination rights."
    )
    first = split_by_regex(text)
    second = split_by_regex(text)
    assert len(first) == len(second)
    for a, b in zip(first, second):
        assert a.clause_id == b.clause_id
        assert a.text == b.text
        assert a.position == b.position
        assert a.section_number == b.section_number
        assert a.clause_type == b.clause_type
