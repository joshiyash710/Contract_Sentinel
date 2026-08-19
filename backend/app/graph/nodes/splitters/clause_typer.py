"""Deterministic clause-type fallback tagger (feature 042).

A pure, offline keyword/phrase tagger that assigns a ``ClauseType`` from clause text.
It exists to fill ``clause_type`` when the ClauseSplitter LLM refinement left it ``None``
(025 Lever-A skip on >40-clause docs, or an off-schema LLM failure), reviving the existing
027 Self-RAG recall floor on large documents with NO dependence on the LLM.

Constitution rules observed:
  §3 — flag + pattern map sourced from app.config (re-exposed as module-level names for
        monkeypatching in tests — same pattern as clause_splitter_agent.py)
  §7 — pure function, TDD-unit-tested offline (no Ollama, no I/O, no RNG)

Only the four recall-floor types are typed (see app.config.DETERMINISTIC_CLAUSE_TYPE_PATTERNS);
typing any other type would have no effect on floor behavior (D2). Conservative multi-word
phrases keep the precision cost bounded (D3). The tagger only ever ADDS a type — it never
removes signal.
"""

from typing import Optional

import app.config as _config  # import module, not names, to allow monkeypatching in tests

from app.graph.state import ClauseType

# Re-expose as module-level names so tests can monkeypatch them (read by bare name below).
DETERMINISTIC_CLAUSE_TYPING_ENABLED = _config.DETERMINISTIC_CLAUSE_TYPING_ENABLED
DETERMINISTIC_CLAUSE_TYPE_PATTERNS = _config.DETERMINISTIC_CLAUSE_TYPE_PATTERNS


def infer_clause_type(text: Optional[str]) -> Optional[ClauseType]:
    """Best-effort deterministic clause type from text, or ``None`` if no confident match.

    Scans the ordered pattern map; the first type with any phrase substring-present in the
    lowercased text wins (fixed order = deterministic multi-match tie-break, EC-1). Empty or
    whitespace-only text yields ``None`` (EC-2). Pure: no I/O, no RNG, no Ollama (AC-6).
    """
    if not text or not text.strip():
        return None  # EC-2
    low = text.lower()
    for ctype_value, phrases in DETERMINISTIC_CLAUSE_TYPE_PATTERNS:
        if any(p in low for p in phrases):
            try:
                return ClauseType(ctype_value)
            except ValueError:
                continue  # defensive: skip a bad config key
    return None
