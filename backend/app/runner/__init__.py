"""
app.runner — Entry-agnostic pipeline orchestration layer.

Exposes the shared run_pipeline core (called by both the API worker and the CLI),
plus the RunResult and NodeProgress types. The graph (builder.py) is untouched;
all new code lives here and in app.api.
"""

from app.runner.core import run_pipeline, RunResult, NodeProgress

__all__ = ["run_pipeline", "RunResult", "NodeProgress"]
