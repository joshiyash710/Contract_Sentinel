"""Unit tests for the eval-harness scorer (feature 026, AC-1,2,3,5,6,7,8 / EC-1,4,5,7).

Pure + deterministic; sidecar fixtures use plain strings (the round-tripped live form).
"""

import math

from eval.harness.scorer import score, DocInput
from eval.harness.schema import GoldClause, GoldDoc


def F(text, risk="high", conf=0.9, section=None, rewrite="rewritten", cid="c"):
    return {
        "clause_id": cid,
        "clause_text": text,
        "section_number": section,
        "position": 1,
        "risk_level": risk,
        "confidence_score": conf,
        "rewrite_state": rewrite,
    }


def G(snippet, should_flag=True, severity="high", section=None):
    return GoldClause(section_number=section, text_snippet=snippet,
                      should_flag=should_flag, expected_severity=severity)


def S(text, final_status="validated", path="local_kb"):
    return {"text": text, "final_status": final_status, "path_taken": path,
            "position": 1, "relevance_verdict": True, "isrel_verdict": True,
            "issup_verdict": final_status == "validated", "retry_count": 0}


def _worked_corpus():
    findings = [
        F("aggregate liability exceed monthly fees", risk="high", conf=0.9, section="3.1", cid="f1"),
        F("indemnify hold harmless all claims", risk="medium", conf=0.6, rewrite="unavailable", cid="f2"),
        F("unrelated notices boilerplate text", risk="low", conf=0.5, rewrite="not_eligible", cid="f3"),
    ]
    gold = GoldDoc(document="d.pdf", source_path="g.json", clauses=[
        G("aggregate liability exceed monthly fees", True, "high", section="3.1"),  # → f1 TP exact
        G("indemnify hold harmless", True, "high"),                                  # → f2 TP within-one
        G("governing law delaware standard", False, None),                           # TN
        G("termination for convenience thirty days", True, "medium"),                # FN (miss)
    ])
    sidecar = [
        S("aggregate liability exceed monthly fees", "validated", "local_kb"),
        S("indemnify hold harmless all claims", "validated", "web_fallback"),
        S("termination for convenience thirty days written notice", "discarded", "web_fallback"),
        S("governing law delaware", "discarded", "local_kb"),
    ]
    report = {"findings": findings, "node_timings": {"clause_splitter": 1.0, "self_rag_validation": 2.0}}
    return DocInput(report=report, sidecar=sidecar, gold=gold)


def test_detection_metrics():  # AC-1, AC-2
    m = score([_worked_corpus()])["detection"]
    assert m["tp"] == 2 and m["fn"] == 1 and m["fp_clean"] == 0 and m["tn"] == 1
    assert m["unlabeled_flags"] == 1
    assert math.isclose(m["precision"], 2 / 3, rel_tol=1e-6)   # 2/(2+0+1)
    assert math.isclose(m["recall"], 2 / 3, rel_tol=1e-6)      # 2/3
    assert math.isclose(m["miss_rate"], 1 / 3, rel_tol=1e-6)
    assert m["false_flag_rate"] == 0.0                         # 0/(0+1)


def test_severity_accuracy():  # AC-3
    s = score([_worked_corpus()])["severity"]
    assert s["n"] == 2
    assert s["exact_accuracy"] == 0.5      # f1 high==high; f2 medium!=high
    assert s["within_one_accuracy"] == 1.0  # both within one rank


def test_calibration_buckets():
    cal = {c["bucket"]: c for c in score([_worked_corpus()])["calibration"]}
    assert cal["[0.5, 0.7)"]["count"] == 2 and cal["[0.5, 0.7)"]["correct_fraction"] == 0.5
    assert cal["[0.85, 1.01)"]["count"] == 1 and cal["[0.85, 1.01)"]["correct_fraction"] == 1.0


def test_diagnostics_from_sidecar():  # AC-5
    d = score([_worked_corpus()])["diagnostics"]
    assert d["self_rag_miss"]["seen_but_discarded"] == 1  # G4 → discarded sidecar
    assert d["self_rag_miss"]["never_split"] == 0
    assert d["crag_path"]["local_kb"] == 2 and d["crag_path"]["web_fallback"] == 2
    assert math.isclose(d["rewrite_availability"], 1 / 3, rel_tol=1e-6)


def test_latency_aggregate():
    lat = score([_worked_corpus()])["latency"]
    assert lat["clause_splitter"]["p50"] == 1.0
    assert lat["self_rag_validation"]["p50"] == 2.0


def test_metrics_shape_and_summary():  # AC-6
    out = score([_worked_corpus()])
    for key in ("corpus", "detection", "severity", "calibration", "diagnostics", "latency"):
        assert key in out


def test_empty_and_undefined_rates():  # AC-7, EC-1, EC-7
    # empty corpus
    out = score([])
    assert out["detection"]["precision"] is None
    assert out["latency"] == {} or out["latency"] is None
    # gold with no should_flag:true → recall undefined (N/A)
    doc = DocInput(
        report={"findings": [], "node_timings": {}},
        sidecar=[],
        gold=GoldDoc(document="d", source_path="g.json", clauses=[G("clean clause", False, None)]),
    )
    m = score([doc])["detection"]
    assert m["recall"] is None and m["miss_rate"] is None


def test_ingest_error_doc_excluded():  # AC-8, EC-5
    good = _worked_corpus()
    bad = DocInput(
        report={"ingest_error": {"message": "could not parse"}, "findings": [], "node_timings": {}},
        sidecar=[],
        gold=GoldDoc(document="bad.pdf", source_path="bad.json", clauses=[G("x risky clause", True, "high")]),
    )
    out = score([good, bad])
    assert "bad" in out["corpus"]["errors"]
    # bad doc's gold clause must NOT inflate FN — detection identical to the good-only run
    assert out["detection"]["fn"] == score([good])["detection"]["fn"]
