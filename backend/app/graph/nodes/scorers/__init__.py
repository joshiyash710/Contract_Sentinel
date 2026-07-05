"""
Scorer modules for the RiskScore node (Node 5).

risk_scorer.py assigns Low/Medium/High severity to a validated finding via a
single generative LLM call. Unlike validators/__init__.py, this package init
hosts no shared helper — risk_scorer.py reuses format_evidence from the
validators package (a dependency-free renderer of the 001 evidence shape) rather
than redefining it.
"""
