"""Feature 028 Part B — pure cross-run variance aggregation (AC-6/7/8/9).

Deterministic, synthetic fixtures — no Ollama, no network, no filesystem.
"""

import pytest

from eval.harness.variance_stats import (
    summarize,
    aggregate_metrics,
    flip_stats,
    verdict_stability,
    build_report,
    format_summary,
)

# ── summarize (AC-6, AC-8) ──────────────────────────────────────────────────────


def test_summarize_basic():
    s = summarize([0.6, 0.8, 1.0])
    assert s["n"] == 3
    assert s["mean"] == pytest.approx(0.8)
    assert s["min"] == 0.6
    assert s["max"] == 1.0
    assert s["std"] == pytest.approx(0.163299, abs=1e-5)  # population std
    assert s["cv"] == pytest.approx(0.204124, abs=1e-5)


def test_summarize_ignores_none_leaves():
    s = summarize([0.5, None, 1.0])
    assert s["n"] == 2
    assert s["mean"] == pytest.approx(0.75)


def test_summarize_cv_na_when_mean_zero():
    s = summarize([0.0, 0.0, 0.0])
    assert s["mean"] == 0.0
    assert s["cv"] is None  # div-by-zero guard


def test_summarize_single_run_std_zero_cv_none():
    s = summarize([0.7])
    assert s["n"] == 1
    assert s["std"] == 0.0
    assert s["cv"] is None  # n < 2
    assert s["min"] == s["max"] == 0.7


def test_summarize_empty_and_all_none():
    for vals in ([], [None, None]):
        s = summarize(vals)
        assert s["n"] == 0
        assert s["mean"] is None
        assert s["cv"] is None


# ── aggregate_metrics (AC-6, AC-8) ──────────────────────────────────────────────


def _metrics(precision, recall, exact):
    return {
        "detection": {
            "precision": precision,
            "recall": recall,
            "f1": None,
            "miss_rate": None,
            "false_flag_rate": None,
        },
        "severity": {"exact_accuracy": exact, "within_one_accuracy": None},
    }


def test_aggregate_metrics_across_runs():
    runs = [_metrics(1.0, 0.6, 0.4), _metrics(1.0, 0.8, 0.6)]
    agg = aggregate_metrics(runs)
    assert agg["runs"] == 2
    assert agg["detection"]["recall"]["mean"] == pytest.approx(0.7)
    assert agg["detection"]["precision"]["std"] == 0.0  # both 1.0
    assert agg["severity"]["exact_accuracy"]["mean"] == pytest.approx(0.5)


def test_aggregate_metrics_empty_runs():
    agg = aggregate_metrics([])
    assert agg["runs"] == 0
    assert agg["detection"]["recall"]["n"] == 0


# ── flip_stats (AC-7, AC-8) ─────────────────────────────────────────────────────


def test_flip_stats_unstable_clause():
    per_run = [
        {"a": True, "b": False, "c": True},
        {"a": True, "b": True, "c": False},
    ]
    fs = flip_stats(per_run)
    assert fs["total"] == 3
    assert fs["stable_caught"] == 1  # a caught in both
    assert fs["stable_missed"] == 0
    assert fs["unstable"] == 2  # b and c flip
    assert fs["per_clause"]["a"] == pytest.approx(1.0)
    assert fs["per_clause"]["b"] == pytest.approx(0.5)


def test_flip_stats_single_run_all_stable():
    fs = flip_stats([{"a": True, "b": False}])
    assert fs["stable_caught"] == 1
    assert fs["stable_missed"] == 1
    assert fs["unstable"] == 0


def test_flip_stats_empty():
    fs = flip_stats([])
    assert fs["total"] == 0
    assert fs["unstable"] == 0


# ── verdict_stability (AC-8) ────────────────────────────────────────────────────


def test_verdict_stability_partial():
    per_run = [
        {"a": ("validated", "high"), "b": ("discarded", None)},
        {"a": ("validated", "high"), "b": ("validated", "low")},
    ]
    vs = verdict_stability(per_run)
    assert vs["total"] == 2
    assert vs["stable"] == 1  # a identical, b differs
    assert vs["fraction"] == pytest.approx(0.5)


def test_verdict_stability_zero_runs_insufficient():
    vs = verdict_stability([])
    assert vs["fraction"] is None


# ── build_report + format_summary (AC-9) ────────────────────────────────────────


def test_build_report_and_summary_non_empty():
    runs = [_metrics(1.0, 0.6, 0.4), _metrics(1.0, 0.8, 0.6)]
    caught = [{"a": True, "b": False}, {"a": True, "b": True}]
    verdicts = [{"a": ("validated", "high")}, {"a": ("validated", "high")}]
    report = build_report(runs, caught, verdicts)
    assert report["runs"] == 2
    assert "detection" in report["metrics"]
    assert report["flip"]["total"] == 2

    text = format_summary(report)
    assert isinstance(text, str) and text.strip()
    assert "±" in text
    assert "CV" in text
