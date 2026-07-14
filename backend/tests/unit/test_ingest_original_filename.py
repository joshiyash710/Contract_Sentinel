"""
Feature 018: ingest_agent prefers a runner-seeded original_filename over deriving it from
the document path, and falls back to the basename when not seeded.
"""

from app.graph.nodes.ingest_agent import ingest_agent


def test_ingest_prefers_seeded_name(tmp_path):
    # A real .docx so parsing doesn't error before we read original_filename; but even a
    # parse failure returns the error dict carrying original_filename, so assert on that.
    p = tmp_path / "abc123.docx"
    p.write_bytes(b"not a real docx")
    out = ingest_agent({"document_path": str(p), "original_filename": "Real Contract.docx"})
    assert out["original_filename"] == "Real Contract.docx"


def test_ingest_falls_back_to_basename(tmp_path):
    p = tmp_path / "abc123.docx"
    p.write_bytes(b"not a real docx")
    out = ingest_agent({"document_path": str(p)})
    assert out["original_filename"] == "abc123.docx"
