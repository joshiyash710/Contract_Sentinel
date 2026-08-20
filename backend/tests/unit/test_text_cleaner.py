"""Unit tests for the feature-044 document-chrome cleaner.

Pure, offline (no Ollama/IO). Covers AC-1/AC-2 (EDGAR footers removed), AC-3 (negative controls —
[***] and real "Source" text preserved), AC-4/EC-2 (mid-line excision), EC-1 (adjacent page number),
AC-6 (idempotence), AC-7 (determinism), EC-6 (empty).
"""

from app.graph.nodes.ingest.text_cleaner import strip_document_chrome


# ── AC-1 / AC-2: footers of various SEC form ids removed ────────────────────
def test_strips_arconic_10_12b_canonical():
    text = (
        "1. Definitions. The following terms apply.\n"
        "Source: ARCONIC ROLLED PRODUCTS CORP, 10-12B, 12/17/2019\n"
        "2. Term. This Agreement is effective on the date below."
    )
    out = strip_document_chrome(text)
    assert "Source: ARCONIC" not in out
    assert "1. Definitions. The following terms apply." in out
    assert "2. Term. This Agreement is effective on the date below." in out


def test_strips_various_form_ids():
    for footer in (
        "Source: FOO CORP, 8-K, 1/7/2019",
        "Source: BAR INC, 10-Q, 11/8/2018",
        "Source: BAZ CO, S-1, 9/20/2019",
        "Source: QUX LLC, 10-KA, 12/2/2019",
        "Source: ACME, EX-10.2, 1/7/2019",
        "Source: NUANCE, F-1, 3/3/2017",
        "Source: XYZ, 1-A, 8/8/2019",
        "Source: PFHOSPITALITY GROUP INC, 10-12G, 9/23/2015",
    ):
        text = f"Clause body before.\n{footer}\nClause body after."
        out = strip_document_chrome(text)
        assert footer not in out, footer
        assert "Clause body before." in out and "Clause body after." in out


# ── AC-3: negative controls (load-bearing — never strip real content) ───────
def test_preserves_source_code_prose():
    text = "Source code shall be delivered to Buyer upon acceptance."
    assert strip_document_chrome(text) == text


def test_preserves_redaction_markers():
    text = "The purchase price shall be [***] per unit for the Term."
    assert strip_document_chrome(text) == text


def test_preserves_prose_with_source_and_form_like_tokens():
    text = "Buyer may draw on any Source of funds, Section 3, dated material notwithstanding."
    assert strip_document_chrome(text) == text


def test_preserves_bare_number_not_adjacent_to_footer():
    text = "Some clause.\n12\nAnother clause."
    assert strip_document_chrome(text) == text


# ── AC-4 / EC-2: mid-line excision keeps the substantive remainder ──────────
def test_midline_footer_excised_keeps_remainder():
    text = "9 Source: ARMSTRONG FLOORING, INC., 8-K, 1/7/2019 directors, officers, agents"
    out = strip_document_chrome(text)
    assert "Source: ARMSTRONG" not in out
    assert "directors, officers, agents" in out


# ── EC-1: bare page-number line hugging a footer is dropped ─────────────────
def test_adjacent_page_number_dropped():
    text = "Real clause text.\nSource: FOO CORP, 8-K, 1/7/2019\n12\nNext clause."
    out = strip_document_chrome(text)
    assert "Source: FOO" not in out
    assert "\n12\n" not in out and out.strip() != ""
    assert "Real clause text." in out and "Next clause." in out


# ── AC-6 idempotence (whole-line AND mid-line) + AC-7 determinism + EC-6 ─────
def test_idempotent_whole_line():
    text = "Body.\nSource: FOO CORP, 10-Q, 1/1/2020\nMore body."
    once = strip_document_chrome(text)
    assert strip_document_chrome(once) == once


def test_idempotent_mid_line():
    text = "9 Source: ARMSTRONG FLOORING, INC., 8-K, 1/7/2019 directors and officers"
    once = strip_document_chrome(text)
    assert strip_document_chrome(once) == once


def test_deterministic_repeated_calls():
    text = "A.\nSource: FOO CORP, 8-K, 1/7/2019\nB."
    first = strip_document_chrome(text)
    for _ in range(5):
        assert strip_document_chrome(text) == first


def test_empty_and_whitespace_unchanged():
    assert strip_document_chrome("") == ""
    assert strip_document_chrome("   \n\t\n ") == "   \n\t\n "


def test_no_artifacts_is_noop():
    text = "1. Scope.\nThe parties agree as follows.\n2. Payment.\nNet 30 days."
    assert strip_document_chrome(text) == text
