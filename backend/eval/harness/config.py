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
