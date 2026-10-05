"""
Feature 055 — PDF clause source-locator capture. Backend unit tests.

Covers: parser dict-extraction + byte-identical-off (AC-1/AC-2), chrome-strip tracked deletions + span
remap (AC-6), regex char ranges (AC-3), grouping range-merge + text-emit None (AC-4/AC-5), locator
stamping + map-clear + degrade (AC-7/AC-8/AC-9/AC-11), and report pass-through (AC-10/AC-13).
"""

import io
from unittest.mock import MagicMock

import pytest
from reportlab.pdfgen import canvas

import app.graph.nodes.parsers.pdf_parser as pdf_mod
from app.graph.nodes.parsers.pdf_parser import parse_pdf
import app.graph.nodes.ingest.text_cleaner as tc
import app.graph.nodes.clause_splitter_agent as cs_mod
from app.graph.nodes.clause_splitter_agent import clause_splitter_agent, locator_from_range
from app.graph.nodes.splitters.regex_splitter import split_by_regex


def _make_pdf(path, pages):
    """pages: list of list[str] lines per page."""
    c = canvas.Canvas(str(path))
    for lines in pages:
        y = 750
        for ln in lines:
            c.drawString(72, y, ln)
            y -= 20
        c.showPage()
    c.save()


# ── Parser (AC-1 / AC-2) ─────────────────────────────────────────────────────────
def _dense_page(tag):
    # ~15 lines of real text so char density clears MIN_CHAR_DENSITY_THRESHOLD (no OCR).
    return [f"{tag} line {i}: the parties agree to the following contract terms and conditions." for i in range(15)]


def test_ac1_parser_captures_page_spans(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_mod, "PDF_SOURCE_LOCATOR_ENABLED", True)
    pdf = tmp_path / "doc.pdf"
    page1 = _dense_page("Alpha")
    page2 = _dense_page("Bravo")
    page2[0] = "Bravo marker line: unique token here."  # a known word on page 2
    _make_pdf(pdf, [page1, page2])
    res = parse_pdf(str(pdf), timeout_seconds=30)
    assert res.ocr_used is False  # dense text → direct extraction, not OCR

    assert res.page_spans is not None and len(res.page_spans) > 0
    # a known word → covering span on the right page with an in-page bbox
    idx = res.text.index("Bravo")
    covering = [s for s in res.page_spans if s["start"] <= idx < s["end"]]
    assert covering, "no span covers the known offset"
    sp = covering[0]
    assert sp["page"] == 2
    assert len(sp["bbox"]) == 4 and sp["bbox"][0] >= 0


def test_ac2_flag_off_byte_identical(tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, [["Alpha one."], ["Bravo two."]])
    monkeypatch.setattr(pdf_mod, "PDF_SOURCE_LOCATOR_ENABLED", False)
    off = parse_pdf(str(pdf), timeout_seconds=30)
    assert off.page_spans is None
    # text equals the plain path
    import fitz

    doc = fitz.open(str(pdf))
    plain = "\n".join(p.get_text() for p in doc)
    doc.close()
    assert off.text == plain


# ── chrome-strip tracked + remap (AC-6) ───────────────────────────────────────────
def test_ac6_tracked_deletions_and_remap_worked_example():
    # "ABCDEF\n<footer>\nGHIJ" — the footer line is dropped; GHIJ must remap correctly.
    footer = "Source: ACME, 10-K, 1/2/2020"
    text = f"ABCDEF\n{footer}\nGHIJ"
    cleaned, deletions = tc.strip_document_chrome_tracked(text)
    assert cleaned == "ABCDEF\nGHIJ"
    # wrapper is byte-identical
    assert tc.strip_document_chrome(text) == cleaned

    # a span over "GHIJ" in ORIGINAL coords
    g = text.index("GHIJ")
    spans = [{"start": g, "end": g + 4, "page": 1, "bbox": [0, 0, 1, 1]}]
    remapped = tc.remap_spans(spans, deletions)
    assert len(remapped) == 1
    r = remapped[0]
    assert cleaned[r["start"]:r["end"]] == "GHIJ"

    # a span fully inside the removed footer is dropped
    f = text.index(footer)
    inside = [{"start": f, "end": f + 5, "page": 1, "bbox": [0, 0, 1, 1]}]
    assert tc.remap_spans(inside, deletions) == []


# ── regex char ranges (AC-3) ──────────────────────────────────────────────────────
def test_ac3_regex_clause_char_ranges():
    text = "1. First clause body.\n2. Second clause body.\n3. Third clause body."
    clauses = split_by_regex(text)
    assert len(clauses) >= 2
    for c in clauses:
        assert c.char_start is not None and c.char_end is not None
        # the stored (stripped) text is contained in the raw char range
        assert c.text.strip()[:10] in text[c.char_start:c.char_end]


# ── locator_from_range unit (AC-7 / AC-8 shape) ───────────────────────────────────
def test_locator_from_range_collects_pages_and_spans():
    page_spans = [
        {"start": 0, "end": 10, "page": 1, "bbox": [0, 0, 1, 1]},
        {"start": 10, "end": 20, "page": 1, "bbox": [0, 2, 1, 3]},
        {"start": 20, "end": 30, "page": 2, "bbox": [0, 0, 1, 1]},
    ]
    loc = locator_from_range(5, 25, page_spans)  # crosses page 1→2
    assert loc["pages"] == [1, 2]
    assert len(loc["spans"]) == 3
    assert all(sp["page"] in loc["pages"] for sp in loc["spans"])
    # empty / None cases
    assert locator_from_range(None, None, page_spans) is None
    assert locator_from_range(1000, 1010, page_spans) is None


# ── clause_splitter stamping + clear + degrade (AC-7/AC-9/AC-11) ───────────────────
def _splitter_state(text, page_spans=None):
    s = {"document_id": "d1", "ingest_error": None, "extracted_text": text}
    if page_spans is not None:
        s["page_spans"] = page_spans
    return s


def test_ac7_ac9_stamp_and_clear(monkeypatch):
    monkeypatch.setattr(cs_mod, "PDF_SOURCE_LOCATOR_ENABLED", True)
    # identity refiner so regex char ranges survive
    monkeypatch.setattr(cs_mod, "refine_with_llm", lambda clauses, *a, **k: clauses)
    text = "1. First clause body text here.\n2. Second clause body text here."
    # page_spans covering the whole text on page 1
    page_spans = [{"start": 0, "end": len(text), "page": 1, "bbox": [0, 0, 100, 100]}]
    out = clause_splitter_agent(_splitter_state(text, page_spans))

    assert out.get("page_spans") is None  # AC-9 — transient map cleared
    locs = [rec.get("source_locator") for rec in out["clauses"].values()]
    assert all(l is not None and l["pages"] == [1] for l in locs)  # AC-7


def test_ac11_degrade_no_page_spans(monkeypatch):
    monkeypatch.setattr(cs_mod, "PDF_SOURCE_LOCATOR_ENABLED", True)
    monkeypatch.setattr(cs_mod, "refine_with_llm", lambda clauses, *a, **k: clauses)
    text = "1. First clause.\n2. Second clause."
    out = clause_splitter_agent(_splitter_state(text, page_spans=None))  # DOCX/OCR-like: no map
    for rec in out["clauses"].values():
        assert rec.get("source_locator") is None


def test_flag_off_no_locator_no_clear(monkeypatch):
    monkeypatch.setattr(cs_mod, "PDF_SOURCE_LOCATOR_ENABLED", False)
    monkeypatch.setattr(cs_mod, "refine_with_llm", lambda clauses, *a, **k: clauses)
    text = "1. First clause.\n2. Second clause."
    out = clause_splitter_agent(_splitter_state(text, page_spans=[{"start": 0, "end": 5, "page": 1, "bbox": [0, 0, 1, 1]}]))
    assert "page_spans" not in out  # flag off → no clear key added
    for rec in out["clauses"].values():
        assert "source_locator" not in rec


# ── report pass-through (AC-10 / AC-13) ───────────────────────────────────────────
def test_ac10_ac13_source_locator_passes_through_to_report():
    from app.graph.nodes.renderers.report_assembler import assemble_report
    from app.graph.state import ValidationStatus

    loc = {"pages": [1], "spans": [{"page": 1, "bbox": [0, 0, 10, 10]}]}
    state = {
        "document_id": "d1",
        "clauses": {
            "clause_001": {
                "text": "A risky clause.",
                "position": 1,
                "final_status": ValidationStatus.VALIDATED,
                "source_locator": loc,
            }
        },
    }
    report = assemble_report(state, generated_at="t", evidence_text_max_chars=2000)
    assert report.findings[0].source_locator == loc


# ── llm_refiner range threading (AC-4 / AC-5) ─────────────────────────────────────
def test_ac4_grouping_merges_char_ranges():
    from app.graph.nodes.splitters import ClauseBoundary
    from app.graph.nodes.splitters.llm_refiner import _build_grouped_clause

    segs = {
        1: ClauseBoundary("clause_001", "seg one", 1, None, None, char_start=0, char_end=10),
        2: ClauseBoundary("clause_002", "seg two", 2, None, None, char_start=10, char_end=25),
    }
    merged = _build_grouped_clause(1, [1, 2], {"indices": [1, 2], "clause_type": None}, segs)
    assert merged.char_start == 0 and merged.char_end == 25  # min/max over the group


def test_ac5_text_emit_path_has_none_ranges():
    from app.graph.nodes.splitters import ClauseBoundary
    from app.graph.nodes.splitters.llm_refiner import _parse_response
    import json

    regex = [ClauseBoundary("clause_001", "Original clause text here.", 1, None, None, char_start=0, char_end=26)]
    raw = json.dumps({"clauses": [{"text": "Original clause text here.", "section_number": None, "clause_type": None}]})
    out = _parse_response(raw, regex)
    assert out[0].char_start is None and out[0].char_end is None  # rewritten text → no offsets
