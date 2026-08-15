"""Unit tests for the per-clause-type detection breakdown (feature 041, AC-7).

Pure + deterministic. Verifies `detection_by_type` groups on the RAW `clause_type`
string (no enum coercion; `None` → "unspecified") and that summing the per-type
tallies reproduces the aggregate `detection` tallies (the aggregate-consistency invariant).
"""

import math

from eval.harness.scorer import score, DocInput
from eval.harness.schema import GoldClause, GoldDoc


def F(text, risk="high", conf=0.9, cid="c"):
    return {"clause_id": cid, "clause_text": text, "section_number": None,
            "position": 1, "risk_level": risk, "confidence_score": conf,
            "rewrite_state": "rewritten"}


def G(snippet, should_flag=True, severity="high", clause_type=None):
    return GoldClause(section_number=None, text_snippet=snippet, should_flag=should_flag,
                      expected_severity=severity, clause_type=clause_type)


def _typed_corpus():
    """Hand-worked, mixed-clause_type corpus:

    liability   : tp(f1) + fn(unmatched)          → recall 1/2, miss 1/2, no clean → false_flag None
    unspecified : tp(f2)                           → recall 1.0, miss 0.0
    governing_law (a raw CUAD-style free-text label, clean): tn only → recall None, false_flag 0.0
    """
    findings = [
        F("aggregate liability exceed monthly fees", risk="high", cid="f1"),
        F("broad confidentiality survives perpetually", risk="medium", cid="f2"),
    ]
    gold = GoldDoc(document="d.pdf", source_path="g.json", clauses=[
        G("aggregate liability exceed monthly fees", True, "high", clause_type="liability"),
        G("uncapped indemnification all losses", True, "high", clause_type="liability"),
        G("broad confidentiality survives perpetually", True, "medium", clause_type=None),
        G("governing law is delaware", False, None, clause_type="governing_law"),
    ])
    report = {"findings": findings, "node_timings": {}}
    return DocInput(report=report, sidecar=[], gold=gold)


def test_detection_by_type_keys():
    bt = score([_typed_corpus()])["detection_by_type"]
    # Raw label strings, untyped bucketed as "unspecified"; no enum coercion.
    assert set(bt) == {"liability", "unspecified", "governing_law"}


def test_per_type_rates():
    bt = score([_typed_corpus()])["detection_by_type"]

    liab = bt["liability"]
    assert liab["n"] == 2
    assert math.isclose(liab["recall"], 0.5)
    assert math.isclose(liab["miss_rate"], 0.5)
    assert liab["false_flag_rate"] is None          # no clean liability clauses → undefined
    assert math.isclose(liab["severity_exact"], 1.0)   # f1 high == gold high
    assert math.isclose(liab["severity_within"], 1.0)

    unspec = bt["unspecified"]
    assert unspec["n"] == 1
    assert unspec["recall"] == 1.0
    assert unspec["miss_rate"] == 0.0

    gl = bt["governing_law"]
    assert gl["n"] == 1
    assert gl["recall"] is None                     # no should_flag:true of this type
    assert gl["miss_rate"] is None
    assert gl["false_flag_rate"] == 0.0             # 0 / (0 clean-flagged + 1 clean-clean)


def test_aggregate_equals_pooled_per_type():  # AC-7 core invariant
    out = score([_typed_corpus()])
    det, bt = out["detection"], out["detection_by_type"]
    assert det["tp"] == sum(t["tp"] for t in bt.values())
    assert det["fn"] == sum(t["fn"] for t in bt.values())
    assert det["fp_clean"] == sum(t["fp_clean"] for t in bt.values())
    assert det["tn"] == sum(t["tn"] for t in bt.values())


def test_global_precision_stays_aggregate_only():
    # Per-type dicts must NOT carry a precision key (untyped unmatched findings make it ill-defined).
    bt = score([_typed_corpus()])["detection_by_type"]
    for t in bt.values():
        assert "precision" not in t
