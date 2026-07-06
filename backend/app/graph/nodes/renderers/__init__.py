"""
Renderer modules for the ReportAgent node (Node 7).

report_assembler.py turns the TypedDict ContractState into a validated Pydantic
ContractReport (validated-only findings, ordered by position) and derives the
evidence_trail rows. markdown_renderer.py renders that model to a Markdown string.
Both are PURE — no file I/O, no LLM, no state mutation — so all report I/O and
failure handling live in report_agent.py. Mirrors the scorers/ / drafters/ /
validators/ / retrievers/ sub-package layout.
"""

from app.graph.nodes.renderers.report_assembler import (
    assemble_report,
    build_evidence_trail,
)
from app.graph.nodes.renderers.markdown_renderer import render_markdown

__all__ = ["assemble_report", "build_evidence_trail", "render_markdown"]
