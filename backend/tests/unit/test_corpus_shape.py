"""Unit tests for corpus-record shape + additive-metadata preservation (feature 041, AC-2).

Pure — no faiss/ollama/app import. Guards that build_kb's `_load_corpus` preserves additive keys into
`clauses_meta.jsonl` (via the shared `eval.harness.corpus_check.load_corpus_records`) and that
`validate_corpus` enforces the required/additive contract (required keys present; additive keys are
optional but, when present, non-empty strings — absent, never null).
"""

import json

import pytest

from eval.harness.corpus_check import CorpusError, load_corpus_records, validate_corpus


BONTERMS = {"snippet_text": "The parties agree to the following terms and conditions herein.",
            "source_reference": "Bonterms Cloud Terms (v1.0) §1 — The Agreement"}
CUAD = {"snippet_text": "In no event shall either party be liable for indirect damages.",
        "source_reference": "CUAD: Foo Distribution Agreement",
        "clause_type": "limitation_of_liability", "source_license": "CC BY 4.0"}


def test_validate_accepts_mixed():
    validate_corpus([BONTERMS, CUAD])  # must not raise


def test_required_keys_enforced():
    with pytest.raises(CorpusError):
        validate_corpus([{"snippet_text": "x only"}])                       # missing source_reference
    with pytest.raises(CorpusError):
        validate_corpus([{"snippet_text": "   ", "source_reference": "r"}])  # empty snippet


def test_null_additive_key_rejected():
    # A present-but-null additive key violates the "absent, not null" contract.
    with pytest.raises(CorpusError):
        validate_corpus([{**BONTERMS, "clause_type": None}])


def test_nonstring_additive_key_rejected():
    with pytest.raises(CorpusError):
        validate_corpus([{**CUAD, "clause_type": 123}])


def test_load_preserves_additive_keys_into_sidecar():
    # The returned records are exactly what build_kb writes to clauses_meta.jsonl — additive keys
    # MUST survive (guards the _load_corpus fix), while Bonterms records stay exactly two-keyed.
    blob = "\n".join(json.dumps(r) for r in (BONTERMS, CUAD))
    recs = load_corpus_records(blob)
    assert len(recs) == 2
    assert set(recs[0]) == {"snippet_text", "source_reference"}        # no null clause_type injected
    assert recs[1]["clause_type"] == "limitation_of_liability"
    assert recs[1]["source_license"] == "CC BY 4.0"
    validate_corpus(recs)


def test_load_requires_mandatory_keys():
    with pytest.raises(CorpusError):
        load_corpus_records(json.dumps({"snippet_text": "missing ref"}))


def test_load_skips_blank_lines():
    blob = json.dumps(BONTERMS) + "\n\n   \n" + json.dumps(CUAD) + "\n"
    assert len(load_corpus_records(blob)) == 2
