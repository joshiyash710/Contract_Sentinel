"""
Unit tests for app.delivery.report_naming (feature 033).

Pure functions — no I/O, no async. Covers Decisions 1/2/5 and AC-7, AC-9, AC-13,
plus the AC-12 escape rule (escape order: backslash first, then single quote).
"""

import app.config as _config


# ── drive_escape (AC-12) ──────────────────────────────────────────────────────


def test_drive_escape_single_quote():
    from app.delivery.report_naming import drive_escape

    assert drive_escape("O'Brien") == "O\\'Brien"


def test_drive_escape_backslash():
    from app.delivery.report_naming import drive_escape

    assert drive_escape("a\\b") == "a\\\\b"


def test_drive_escape_order_backslash_before_quote():
    """A backslash-then-quote input must escape the backslash first so we do not
    double-escape the quote's inserted backslash."""
    from app.delivery.report_naming import drive_escape

    # input chars: a \ ' b  → a \\ \' b  → a + 3 backslashes + ' + b
    assert drive_escape("a\\'b") == "a\\\\\\'b"


# ── sanitize_stem (AC-13) — assert invariants only ────────────────────────────


def test_sanitize_stem_strips_path_separators():
    from app.delivery.report_naming import sanitize_stem

    out = sanitize_stem("a/b\\c")
    assert "/" not in out
    assert "\\" not in out


def test_sanitize_stem_strips_control_chars():
    from app.delivery.report_naming import sanitize_stem

    out = sanitize_stem("a\x00b\nc\td")
    assert all(ord(ch) >= 32 for ch in out)  # no control chars remain


def test_sanitize_stem_caps_length(monkeypatch):
    from app.delivery import report_naming

    monkeypatch.setattr(_config, "MCP_DRIVE_NAME_MAX_STEM_CHARS", 5)
    out = report_naming.sanitize_stem("abcdefghijklmnop")
    assert len(out) <= 5


# ── report_base_name (Decision 1/2, AC-7, AC-9) ───────────────────────────────


def test_report_base_name_basic():
    from app.delivery.report_naming import report_base_name

    assert (
        report_base_name("Acme MSA.pdf", "a3f1c9e2xxxx")
        == "Acme MSA — Risk Report (a3f1c9)"
    )


def test_report_base_name_no_extension():
    from app.delivery.report_naming import report_base_name

    assert (
        report_base_name("Acme MSA", "a3f1c9e2xxxx")
        == "Acme MSA — Risk Report (a3f1c9)"
    )


def test_report_base_name_blank_falls_back_to_document_id():
    from app.delivery.report_naming import report_base_name

    assert (
        report_base_name("", "a3f1c9e2xxxx")
        == "a3f1c9e2xxxx — Risk Report (a3f1c9)"
    )


def test_report_base_name_all_separators_falls_back_to_document_id():
    """A name that sanitizes to empty must fall back to the full document_id stem (AC-9)."""
    from app.delivery.report_naming import report_base_name

    assert (
        report_base_name("///", "a3f1c9e2xxxx")
        == "a3f1c9e2xxxx — Risk Report (a3f1c9)"
    )


# ── drive_file_name ───────────────────────────────────────────────────────────


def test_drive_file_name_appends_extension():
    from app.delivery.report_naming import drive_file_name

    assert (
        drive_file_name("Acme MSA — Risk Report (a3f1c9)", "json")
        == "Acme MSA — Risk Report (a3f1c9).json"
    )
