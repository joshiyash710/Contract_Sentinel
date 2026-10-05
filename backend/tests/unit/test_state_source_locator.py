"""Feature 055 — AC-12: the transient `page_spans` top-level key is present on the ContractState
TypedDict (there is no automated schema-transcription test; this pins the new annotation)."""

from app.graph.state import ContractState


def test_page_spans_is_a_contractstate_annotation():
    assert "page_spans" in ContractState.__annotations__
