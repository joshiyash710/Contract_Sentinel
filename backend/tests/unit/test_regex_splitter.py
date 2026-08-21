"""
Unit tests for app.graph.nodes.splitters.regex_splitter.split_by_regex().

No mocks, no Ollama, no network — pure regex logic only.
Written BEFORE the implementation (TDD red phase).

Run: python -m pytest tests/unit/test_regex_splitter.py -v
(feature 040 added the spelled-out clause/article/section heading cases — AC-1…AC-10 — to the
original suite; all tests in this file PASS with the current regex_splitter.)
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


def test_split_lettered_sections(monkeypatch):
    """(a), (b), (c) lettered sub-items. Re-pinned for feature 045: with the flag ON these split into
    3 (today's behavior); with the flag OFF (default) a bare sub-list with no higher-level marker above
    it falls to the single-block fallback (EC-1) rather than fragmenting into one clause per item."""
    text = (
        "(a) First obligation\nThe first party shall.\n"
        "(b) Second obligation\nThe second party shall.\n"
        "(c) Third obligation\nThe third party shall."
    )
    # Flag on: legacy behavior — one clause per (a)/(b)/(c).
    monkeypatch.setattr(regex_splitter, "CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS", True)
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 3
    # Flag off (default): no higher marker → kept together via the fallback (EC-1), not fragmented.
    monkeypatch.setattr(regex_splitter, "CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS", False)
    assert len(split_by_regex(text)) == 1


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


# ── Feature 040 — spelled-out ordinal / word clause headings ─────────────────────
# The regex pre-pass previously recognized only digit-numbered / Article N / Section N / §N /
# (a) / a. markers. Contracts using "CLAUSE ONE", "ARTICLE ONE", etc. matched NOTHING and fell
# through to paragraph splitting, catastrophically under-segmenting. These cover the fix.

# The 8 clauses of the observed Student Loan Agreement (SSN replaced with a placeholder — no PII).
_STUDENT_LOAN_CLAUSES = (
    "CLAUSE ONE - PURPOSE: This agreement grants financing to the BORROWER.\n"
    "CLAUSE TWO - TERM: The financing period shall be up to 60 months.\n"
    "CLAUSE THREE - PAYMENT: The BORROWER shall pay monthly installments with 1.2% interest.\n"
    "CLAUSE FOUR - GUARANTEES: The financed asset remains under fiduciary lien until settlement.\n"
    "CLAUSE FIVE - INSURANCE: The BORROWER must contract mandatory insurance.\n"
    "CLAUSE SIX - DEFAULT: Payment delay results in a 2% penalty and 1% monthly late interest.\n"
    "CLAUSE SEVEN - TERMINATION: Breach results in termination regardless of notification.\n"
    "CLAUSE EIGHT - JURISDICTION: The parties elect the courts of New York, NY.\n"
)
_STUDENT_LOAN_PREAMBLE = (
    "STUDENT LOAN AGREEMENT\n"
    "BORROWER: Richard Taylor, SSN no XXX-XX-XXXX.\n"
    "FINANCED AMOUNT: $56,424.00.\n"
)


def test_clause_word_headings_split():
    """AC-1: eight 'CLAUSE <WORD>' headings produce eight boundaries."""
    clauses = split_by_regex(_STUDENT_LOAN_CLAUSES)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 8


def test_clause_word_section_number_captured():
    """AC-2: section_number is the verbatim heading, original casing preserved."""
    clauses = split_by_regex(_STUDENT_LOAN_CLAUSES)
    section_numbers = [c.section_number for c in clauses]
    assert all(sn is not None for sn in section_numbers), section_numbers
    assert section_numbers[0] == "CLAUSE ONE"
    assert section_numbers[5] == "CLAUSE SIX"


def test_article_word_headings_split():
    """AC-3: 'ARTICLE <WORD>' and 'SECTION <WORD>' headings segment symmetrically."""
    article_text = (
        "ARTICLE ONE Definitions\nTerms.\n"
        "ARTICLE TWO Obligations\nDuties.\n"
        "ARTICLE THREE Termination\nExit."
    )
    assert len(split_by_regex(article_text)) == 3
    section_text = (
        "SECTION ONE Scope\nScope text.\n"
        "SECTION TWO Payment\nPayment text.\n"
    )
    assert len(split_by_regex(section_text)) == 2


def test_clause_article_digit_forms():
    """AC-4: digit-numbered CLAUSE/ARTICLE also match (not only spelled-out)."""
    text = (
        "CLAUSE 1 Purpose\nGrant financing.\n"
        "Clause 1.2 Interpretation\nBroad reading.\n"
        "ARTICLE 4 Guarantees\nFiduciary lien."
    )
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 3


def test_clause_heading_case_insensitive():
    """AC-5: 'clause one' / 'Clause One' / 'CLAUSE ONE' behave identically."""
    for variant in ("clause one", "Clause One", "CLAUSE ONE"):
        text = f"{variant} First heading\nBody.\nclause two Second heading\nBody two."
        assert len(split_by_regex(text)) == 2, variant


def test_ordinal_vocabulary_spot_check():
    """spec §8 decision 1: ordinals resolve, and 'twentieth' is not truncated to 'twenty'."""
    # NB: body lines deliberately avoid recital keywords (WHEREAS/RECITALS/BACKGROUND/…) so the
    # only boundaries are the two ordinal headings under test.
    text = (
        "ARTICLE FIRST Preliminary\nIntroductory provisions apply.\n"
        "CLAUSE TWENTIETH Miscellaneous\nGeneral boilerplate follows."
    )
    clauses = split_by_regex(text)
    assert len(clauses) == 2
    assert clauses[0].section_number == "ARTICLE FIRST"
    assert clauses[1].section_number == "CLAUSE TWENTIETH"


def test_existing_markers_no_regression(monkeypatch):
    """AC-6 (feature 040), re-pinned for feature 045: the 5 higher-level markers
    (1./Article/Section/§/WHEREAS) still segment as before; the 2 sub-list markers ((a)/a.) now attach
    to their parent by default and only split when CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS is True."""
    text = (
        "1. Definitions\nTerms defined.\n"
        "Article 5 Obligations\nDuties.\n"
        "Section 1.2 Scope\nScope text.\n"
        "§3 Confidentiality\nSecret.\n"
        "(a) First item\nItem text.\n"
        "a. Lettered item\nMore text.\n"
        "WHEREAS the parties agree to terms herein."
    )
    # Default (045 flag off): the (a)/a. sub-items merge into the preceding "§3" clause → 5 boundaries.
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 5
    # Flag on reproduces the pre-045 behavior byte-for-byte: 7 boundaries.
    monkeypatch.setattr(regex_splitter, "CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS", True)
    assert len(split_by_regex(text)) == 7


def test_first_match_wins_no_double_count():
    """AC-9: 'SECTION 1.2' is captured once (by the pre-existing digit pattern), not doubled."""
    text = "SECTION 1.2 Scope\nScope of the agreement follows here."
    clauses = split_by_regex(text)
    assert len(clauses) == 1
    assert clauses[0].section_number == "Section 1.2" or "1.2" in clauses[0].section_number


def test_clause_prose_no_false_boundary():
    """AC-10: 'Clause' in prose (no number/ordinal) and 'CLAUSEONE' (no space) do NOT split."""
    prose = (
        "Clause headings are for convenience only and shall not affect interpretation. "
        "The word CLAUSEONE is not a heading either."
    )
    clauses = split_by_regex(prose)
    # No new-pattern boundary: single unbroken block → one clause with no section_number.
    assert len(clauses) == 1
    assert clauses[0].section_number is None


def test_clause_twenty_first_partial_match():
    """Reviewer note / spec §5: 'CLAUSE TWENTY-FIRST' matches at 'CLAUSE TWENTY' (documented, not a bug)."""
    text = "CLAUSE TWENTY-FIRST Special\nAn unusual heading beyond the vocabulary."
    clauses = split_by_regex(text)
    assert len(clauses) == 1
    assert clauses[0].section_number == "CLAUSE TWENTY"


def test_student_loan_fixture_24_clauses():
    """AC-7: the 8-clause agreement repeated 3x → 24 boundaries (previously collapsed to 3)."""
    text = _STUDENT_LOAN_PREAMBLE + (_STUDENT_LOAN_CLAUSES * 3)
    clauses = split_by_regex(text)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 24


# ── Feature 045 — enumerated sub-list items stay with their governing clause ─────
import app.graph.nodes.splitters.regex_splitter as regex_splitter  # noqa: E402

_SUBLIST_FIXTURE = (
    "2.4 The Distributor shall not:\n"
    "(a) represent itself as an agent; or\n"
    "(b) pledge the Supplier's credit; or\n"
    "(f) act as the agent or the buying agent, for any goods which are competitive with the Product; or\n"
    "2.5 Next obligation. The Distributor shall keep records."
)


def test_sublist_items_merge_with_stem_by_default():
    """AC-1/AC-2: with the flag at its default (False), the (a)/(b)/(f) sub-items stay attached to
    the '2.4 ... shall not:' stem → exactly 2 clauses (2.4 incl. all sub-items, 2.5)."""
    clauses = split_by_regex(_SUBLIST_FIXTURE)
    _assert_valid_boundaries(clauses)
    assert len(clauses) == 2
    first = clauses[0].text.lower()
    assert "shall not" in first and "competitive with the product" in first  # (f) kept with its stem
    assert "next obligation" in clauses[1].text.lower()


def test_sublist_reversible_flag_on_splits_each_item(monkeypatch):
    """AC-3: with CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS=True (today's behavior), each (a)/(b)/(f)
    opens its own clause and (f) becomes a stem-less fragment."""
    monkeypatch.setattr(regex_splitter, "CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS", True)
    clauses = split_by_regex(_SUBLIST_FIXTURE)
    _assert_valid_boundaries(clauses)
    # 2.4, (a), (b), (f), 2.5 → 5 boundaries.
    assert len(clauses) == 5
    frag = [c for c in clauses if "competitive with the product" in c.text.lower()][0]
    assert "shall not" not in frag.text.lower()  # the (f) fragment lost its governing stem


def test_sublist_no_regression_on_non_sublist_doc(monkeypatch):
    """AC-4: a doc with only 1./Article/§/WHEREAS markers segments identically flag on vs off
    (the removed sub-list patterns never matched it)."""
    text = (
        "1. Definitions\nTerms defined here in detail.\n"
        "Article 5 Obligations\nDuties apply to the parties.\n"
        "§3 Confidentiality\nKeep it secret.\n"
        "WHEREAS the parties agree to these terms herein."
    )
    off = split_by_regex(text)
    monkeypatch.setattr(regex_splitter, "CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS", True)
    on = split_by_regex(text)
    assert [c.section_number for c in off] == [c.section_number for c in on]
    assert [c.text for c in off] == [c.text for c in on]


def test_sublist_alpha_dot_block(monkeypatch):
    """AC-5: an 'a. / b.' enumerated block under a '1.' stem is one clause when False, split when True."""
    text = (
        "1. Restrictions apply as follows.\n"
        "a. do not copy the software; and\n"
        "b. do not reverse engineer the product."
    )
    assert len(split_by_regex(text)) == 1  # default: a./b. absorbed into the "1." clause
    monkeypatch.setattr(regex_splitter, "CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS", True)
    assert len(split_by_regex(text)) == 3  # 1., a., b.


def test_sublist_deterministic_repeated_calls():
    """AC-7: repeated calls on the same input + flag are identical."""
    first = [c.text for c in split_by_regex(_SUBLIST_FIXTURE)]
    for _ in range(5):
        assert [c.text for c in split_by_regex(_SUBLIST_FIXTURE)] == first
