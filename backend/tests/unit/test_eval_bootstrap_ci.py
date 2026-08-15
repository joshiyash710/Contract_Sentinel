"""Unit tests for bootstrap confidence intervals on detection rates (feature 041, AC-8).

Pure + deterministic. The bootstrap resamples DOCUMENTS with replacement (the independent
unit) under a fixed seed, so intervals are reproducible.
"""

from eval.harness.scorer import score, DocInput, bootstrap_detection_ci
from eval.harness.schema import GoldClause, GoldDoc
from eval.harness import config


def F(text, risk="high", cid="c"):
    return {"clause_id": cid, "clause_text": text, "section_number": None, "position": 1,
            "risk_level": risk, "confidence_score": 0.9, "rewrite_state": "rewritten"}


def G(snippet, should_flag=True, severity="high"):
    return GoldClause(section_number=None, text_snippet=snippet, should_flag=should_flag,
                      expected_severity=severity)


def doc(findings, clauses, ingest_error=None):
    report = {"findings": findings, "node_timings": {}}
    if ingest_error:
        report["ingest_error"] = ingest_error
    return DocInput(report=report, sidecar=[],
                    gold=GoldDoc(document="d", source_path="g.json", clauses=clauses))


def _mixed_docs():
    # A: tp (risky, detected); B: fn (risky, missed) + tn (clean, not flagged); C: fp_clean (clean, flagged)
    a = doc([F("uncapped liability clause", cid="a1")], [G("uncapped liability clause", True, "high")])
    b = doc([], [G("hidden auto renewal evergreen", True, "medium"), G("standard notices clause", False, None)])
    c = doc([F("routine governing law clause", cid="c1")], [G("routine governing law clause", False, None)])
    return [a, b, c]


def test_bootstrap_reproducible():  # AC-8 reproducibility
    docs = _mixed_docs()
    ci1 = bootstrap_detection_ci(docs, 500, config.EVAL_BOOTSTRAP_SEED, 0.95)
    ci2 = bootstrap_detection_ci(docs, 500, config.EVAL_BOOTSTRAP_SEED, 0.95)
    assert ci1 == ci2
    assert ci1["n_docs"] == 3


def test_point_estimate_within_ci():  # AC-8 estimate-in-interval
    docs = _mixed_docs()
    out = score(docs)
    det, ci = out["detection"], out["detection_ci"]
    for m in ("recall", "miss_rate", "false_flag_rate", "precision"):
        est, bounds = det[m], ci[m]
        if est is not None and bounds is not None:
            lo, hi = bounds
            assert lo <= est <= hi


def test_all_correct_degenerate():  # AC-8 degenerate → valid [1,1]
    docs = [doc([F("clear high risk uncapped indemnity", cid="x")],
                [G("clear high risk uncapped indemnity", True, "high")])]
    ci = bootstrap_detection_ci(docs, 200, 123, 0.95)
    assert ci["recall"] == [1.0, 1.0]
    assert ci["n_docs"] == 1


def test_undefined_rate_returns_none():  # EC-6
    docs = [doc([], [G("just a clean clause", False, None)])]  # no should_flag:true → recall undefined
    ci = bootstrap_detection_ci(docs, 100, 7, 0.95)
    assert ci["recall"] is None
    assert ci["miss_rate"] is None


def test_ingest_error_excluded():
    good = doc([F("uncapped liability clause", cid="a1")], [G("uncapped liability clause", True, "high")])
    bad = doc([], [G("risky", True, "high")], ingest_error={"message": "x"})
    ci = bootstrap_detection_ci([good, bad], 100, 5, 0.95)
    assert ci["n_docs"] == 1  # bad doc excluded


def test_empty_corpus():
    ci = bootstrap_detection_ci([], 100, 5, 0.95)
    assert ci["n_docs"] == 0
    assert ci["recall"] is None


def test_score_exposes_ci_and_clause_level_n():
    out = score(_mixed_docs())
    assert "detection_ci" in out
    det = out["detection"]
    # clause-level denominators are surfaced next to the rates (distinct from bootstrap n_docs)
    assert det["recall_n"] == det["tp"] + det["fn"]
    assert det["false_flag_n"] == det["fp_clean"] + det["tn"]
    assert out["detection_ci"]["n_docs"] == 3
