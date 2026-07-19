"""Evaluation-harness config constants (feature 026, constitution §3).

Centralized here (not in app/config.py's runtime hot path) but still named constants — never
hardcoded inline in matcher/scorer. Tune against real node_timings / reviewer QA.
"""

# Minimum gold-snippet containment (0..1) for a finding to count as matching a gold clause.
EVAL_MATCH_MIN_OVERLAP: float = 0.6

# Severity ordering for exact + within-one accuracy (RiskLevel.value → rank).
SEVERITY_RANK: dict = {"low": 0, "medium": 1, "high": 2}

# Reliability-table bin edges for confidence_score calibration (last edge > 1.0 to include 1.0).
CONFIDENCE_BUCKETS: list = [0.0, 0.5, 0.7, 0.85, 1.01]

# Number of full harness (run+score) cycles the feature-028 variance driver executes over the gold
# corpus to measure metric variance. N>=3 recommended in the summary; each cycle is multiple minutes
# on the local 8B/6GB box (spec 028 OQ-3). Indicative, not authoritative (026 corpus caveat).
EVAL_VARIANCE_RUNS: int = 5
