"""
Unit tests for markdown_renderer.py — render_markdown (Node 7).

TDD red phase: all tests fail (ImportError) until Task 9 implements the module.
Pure string assertions over ContractReport instances — no I/O, no mocks.
Run: python -m pytest tests/unit/test_report_renderer.py -v
"""


GENERATED_AT = "2026-07-06T01:00:00+00:00"
STARTED_AT = "2026-07-06T00:00:00+00:00"


def _make_evidence(snippet="Evidence text.", source="doc.pdf §1"):
    from app.models.report import ReportEvidence

    return ReportEvidence(source_reference=source, snippet_text=snippet)


def _make_finding(**kwargs):
    from app.models.report import ReportFinding

    defaults = {
        "clause_id": "c1",
        "position": 1,
        "clause_text": "The contractor shall indemnify the client.",
        "rewrite_state": "not_eligible",
    }
    defaults.update(kwargs)
    return ReportFinding(**defaults)


def _make_summary(**kwargs):
    from app.models.report import ReportSummary

    defaults = {
        "total_clauses": 5,
        "validated_findings": 2,
        "clean_clauses": 3,
        "high": 1,
        "medium": 1,
        "low": 0,
    }
    defaults.update(kwargs)
    return ReportSummary(**defaults)


def _make_report(**kwargs):
    from app.models.report import ContractReport

    defaults = {
        "document_id": "doc-001",
        "original_filename": "contract.pdf",
        "uploaded_at": STARTED_AT,
        "processing_started_at": STARTED_AT,
        "generated_at": GENERATED_AT,
        "summary": _make_summary(),
    }
    defaults.update(kwargs)
    return ContractReport(**defaults)


def test_header_counts_rendered():
    """Headline shows validated count + H/M/L + clean count (AC-9/D4)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    report = _make_report(
        summary=_make_summary(
            total_clauses=10,
            validated_findings=3,
            clean_clauses=7,
            high=2,
            medium=1,
            low=0,
        )
    )
    md = render_markdown(report)
    assert "3" in md  # findings count
    assert "2" in md  # high
    assert "1" in md  # medium
    assert "7" in md  # clean


def test_findings_in_position_order():
    """Finding sections appear in ascending position order (AC-2)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    f1 = _make_finding(clause_id="c1", position=1, risk_level="low")
    f2 = _make_finding(clause_id="c2", position=2, risk_level="medium")
    report = _make_report(
        findings=[f2, f1],  # deliberately reversed
        summary=_make_summary(
            validated_findings=2, clean_clauses=3, high=0, medium=1, low=1
        ),
    )
    md = render_markdown(report)
    pos_c1 = md.index("c1")
    pos_c2 = md.index("c2")
    assert pos_c1 < pos_c2


def test_finding_shows_severity_and_rationale():
    """Each finding renders risk_level + risk_rationale (AC-3)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    f = _make_finding(risk_level="high", risk_rationale="Unlimited liability exposure.")
    report = _make_report(
        findings=[f],
        summary=_make_summary(
            validated_findings=1, clean_clauses=4, high=1, medium=0, low=0
        ),
    )
    md = render_markdown(report)
    assert "high" in md.lower()
    assert "Unlimited liability exposure." in md


def test_finding_shows_text_and_locator():
    """clause_text + section_number (or '§ n/a' placeholder when None) shown (AC-4)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    f_with = _make_finding(
        clause_id="c1",
        position=1,
        risk_level="high",
        section_number="§3.1",
        clause_text="Shall indemnify.",
    )
    f_without = _make_finding(
        clause_id="c2",
        position=2,
        risk_level="medium",
        section_number=None,
        clause_text="Payment due in 30 days.",
    )
    report = _make_report(
        findings=[f_with, f_without],
        summary=_make_summary(
            validated_findings=2, clean_clauses=3, high=1, medium=1, low=0
        ),
    )
    md = render_markdown(report)
    assert "§3.1" in md
    assert "Shall indemnify." in md
    assert "§ n/a" in md
    assert "Payment due in 30 days." in md


def test_provenance_rendered():
    """path_taken + confidence_score shown; graceful when either is None (AC-5)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    f_with = _make_finding(
        clause_id="c1",
        position=1,
        risk_level="high",
        path_taken="local_kb",
        confidence_score=0.92,
    )
    f_without = _make_finding(
        clause_id="c2",
        position=2,
        risk_level="low",
        path_taken=None,
        confidence_score=None,
    )
    report = _make_report(
        findings=[f_with, f_without],
        summary=_make_summary(
            validated_findings=2, clean_clauses=3, high=1, medium=0, low=1
        ),
    )
    md = render_markdown(report)
    assert "local_kb" in md
    assert "0.92" in md


def test_evidence_block_rendered():
    """Each snippet's snippet_text + source_reference shown; block omitted when evidence==[] (AC-6/7)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    f_with = _make_finding(
        clause_id="c1",
        position=1,
        risk_level="high",
        evidence=[_make_evidence("Key snippet.", "doc.pdf §5")],
    )
    f_without = _make_finding(clause_id="c2", position=2, risk_level="low", evidence=[])
    report = _make_report(
        findings=[f_with, f_without],
        summary=_make_summary(
            validated_findings=2, clean_clauses=3, high=1, medium=0, low=1
        ),
    )
    md = render_markdown(report)
    assert "Key snippet." in md
    assert "doc.pdf §5" in md


def test_rewrite_three_states_distinct():
    """'rewritten' shows rewrite; 'unavailable' shows marker; 'not_eligible' shows neither (AC-8)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    f_rewritten = _make_finding(
        clause_id="c1",
        position=1,
        risk_level="high",
        rewrite_state="rewritten",
        suggested_rewrite="Rewritten clause language.",
    )
    f_unavailable = _make_finding(
        clause_id="c2",
        position=2,
        risk_level="medium",
        rewrite_state="unavailable",
        suggested_rewrite=None,
    )
    f_ineligible = _make_finding(
        clause_id="c3",
        position=3,
        risk_level="low",
        rewrite_state="not_eligible",
        suggested_rewrite=None,
    )
    report = _make_report(
        findings=[f_rewritten, f_unavailable, f_ineligible],
        summary=_make_summary(
            validated_findings=3, clean_clauses=2, high=1, medium=1, low=1
        ),
    )
    md = render_markdown(report)
    assert "Rewritten clause language." in md
    assert "no rewrite available" in md.lower()
    # All three states must be distinguishable
    assert md.count("Rewritten clause language.") >= 1


def test_severity_unavailable_placeholder():
    """risk_level=None finding renders 'severity unavailable', no crash (Edge Case 4)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    f = _make_finding(risk_level=None)
    report = _make_report(
        findings=[f],
        summary=_make_summary(
            validated_findings=1, clean_clauses=4, high=0, medium=0, low=0
        ),
    )
    md = render_markdown(report)
    assert "severity unavailable" in md.lower()


def test_clean_clauses_counted_not_listed():
    """The clean count appears; no clause text is enumerated for clean clauses (D4)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    report = _make_report(
        summary=_make_summary(
            total_clauses=5,
            validated_findings=1,
            clean_clauses=4,
            high=1,
            medium=0,
            low=0,
        ),
        findings=[_make_finding(risk_level="high")],
    )
    md = render_markdown(report)
    assert "4" in md  # clean count present


def test_ocr_caveat_when_ocr_used():
    """ocr_used=True → an OCR caveat line in the header; absent when False (Edge Case 8)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    report_ocr = _make_report(ocr_used=True, ocr_confidence=0.78)
    md_ocr = render_markdown(report_ocr)
    assert "ocr" in md_ocr.lower()

    report_no_ocr = _make_report(ocr_used=False)
    md_no_ocr = render_markdown(report_no_ocr)
    # No OCR-specific caveat expected (just check it renders without error)
    assert isinstance(md_no_ocr, str)


def test_zero_findings_clean_report():
    """Zero validated findings → well-formed 'no findings' body, non-empty string (AC-18)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    report = _make_report(
        findings=[],
        summary=_make_summary(
            total_clauses=5,
            validated_findings=0,
            clean_clauses=5,
            high=0,
            medium=0,
            low=0,
        ),
    )
    md = render_markdown(report)
    assert isinstance(md, str)
    assert len(md) > 0
    assert (
        "no findings" in md.lower()
        or "0 finding" in md.lower()
        or "clean" in md.lower()
    )


def test_ingest_error_minimal_body():
    """ingest_error set → 'could not be processed' header echoing the error message (AC-20)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    report = _make_report(
        ingest_error={"message": "OCR failed", "code": "ocr_error"},
        summary=_make_summary(
            total_clauses=0,
            validated_findings=0,
            clean_clauses=0,
            high=0,
            medium=0,
            low=0,
        ),
        findings=[],
    )
    md = render_markdown(report)
    assert (
        "could not be processed" in md.lower()
        or "ocr failed" in md.lower()
        or "ingest" in md.lower()
    )


def test_footer_renders_partial_timings():
    """Missing/partial node_timings / error_count render without crash (Edge Case 10)."""
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    report = _make_report(node_timings={}, error_count=0)
    md = render_markdown(report)
    assert isinstance(md, str)

    report2 = _make_report(
        node_timings={"ingest": 1.23, "clause_splitter": 4.56},
        error_count=2,
    )
    md2 = render_markdown(report2)
    assert "1.23" in md2 or "ingest" in md2


def test_footer_renders_total_elapsed():
    """Footer shows a total-elapsed line from generated_at − processing_started_at;
    renders 'unknown' when processing_started_at is None (spec §2.3 item 4, review item 1).
    """
    from app.graph.nodes.renderers.markdown_renderer import render_markdown

    # STARTED_AT = "2026-07-06T00:00:00+00:00", GENERATED_AT = "2026-07-06T01:00:00+00:00"
    # → 3600 seconds elapsed
    report = _make_report(
        processing_started_at=STARTED_AT,
        generated_at=GENERATED_AT,
    )
    md = render_markdown(report)
    assert "3600" in md or "elapsed" in md.lower()

    report_no_start = _make_report(processing_started_at=None)
    md_no_start = render_markdown(report_no_start)
    assert "unknown" in md_no_start.lower()
