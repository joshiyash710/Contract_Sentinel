"""Gold-label schema + run-artifact readers for the evaluation harness (feature 026).

Gold files (backend/eval/gold/*.json) are hand-authored clause-level labels; run artifacts
(report JSON + verdict sidecar + manifest) are produced by run.py. All readers are pure and
import nothing from app.* (keeps score.py offline — AC-6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_SEVERITIES = {"low", "medium", "high"}

# Raw-state clause-record keys kept in the verdict sidecar (NOT report boundary names).
SIDECAR_KEYS = (
    "text",
    "position",
    "section_number",
    "final_status",
    "relevance_verdict",
    "isrel_verdict",
    "issup_verdict",
    "retry_count",
    "path_taken",
)


class GoldError(ValueError):
    """Raised when a gold file is malformed."""


@dataclass
class GoldClause:
    section_number: Optional[str]
    text_snippet: str
    should_flag: bool
    expected_severity: Optional[str]  # "low"|"medium"|"high"|None
    clause_type: Optional[str] = None
    note: Optional[str] = None


@dataclass
class GoldDoc:
    document: str  # path to the source contract (backend-relative)
    clauses: List[GoldClause]
    notes: Optional[str] = None
    source_path: Optional[str] = None  # the gold file's own path (for the gold-id)

    @property
    def gold_id(self) -> str:
        return Path(self.source_path).stem if self.source_path else Path(self.document).stem


def load_gold(path: str | Path) -> GoldDoc:
    """Load + validate one gold file. Raises GoldError on a malformed shape."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise GoldError(f"{p}: not readable JSON: {exc}") from exc

    if not isinstance(raw, dict) or "document" not in raw or "clauses" not in raw:
        raise GoldError(f"{p}: gold file must have 'document' and 'clauses'")

    clauses: List[GoldClause] = []
    for i, c in enumerate(raw["clauses"]):
        loc = c.get("locator") or {}
        snippet = loc.get("text_snippet")
        if not snippet:
            raise GoldError(f"{p}: clause[{i}] missing locator.text_snippet")
        if "should_flag" not in c or not isinstance(c["should_flag"], bool):
            raise GoldError(f"{p}: clause[{i}] missing/invalid should_flag (bool)")
        sev = c.get("expected_severity")
        if sev is not None:
            sev = str(sev).strip().lower()
            if sev not in _SEVERITIES:
                raise GoldError(
                    f"{p}: clause[{i}] expected_severity {sev!r} not in {_SEVERITIES} or null"
                )
        clauses.append(
            GoldClause(
                section_number=loc.get("section_number"),
                text_snippet=str(snippet),
                should_flag=bool(c["should_flag"]),
                expected_severity=sev,
                clause_type=c.get("clause_type"),
                note=c.get("note"),
            )
        )

    return GoldDoc(
        document=str(raw["document"]),
        clauses=clauses,
        notes=raw.get("notes"),
        source_path=str(p),
    )


def load_gold_dir(gold_dir: str | Path) -> List[GoldDoc]:
    return [load_gold(p) for p in sorted(Path(gold_dir).glob("*.json"))]


def build_sidecar(final_state_clauses: Dict[str, Dict[str, Any]]) -> List[dict]:
    """Slice the raw final_state['clauses'] into JSON-serializable verdict records.

    final_status / path_taken are str-subclass enums (ValidationStatus / RetrievalPath), so
    json.dump emits their value strings automatically — no conversion needed; do NOT str() them.
    """
    out: List[dict] = []
    for cid, rec in final_state_clauses.items():
        row = {"clause_id": cid}
        for k in SIDECAR_KEYS:
            row[k] = rec.get(k)
        out.append(row)
    return out


# ── Run-artifact readers (pure JSON) ────────────────────────────────────────


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_report(json_path: str | Path) -> dict:
    return read_json(json_path)


def read_sidecar(path: str | Path) -> List[dict]:
    return read_json(path)


def read_manifest(run_dir: str | Path) -> dict:
    return read_json(Path(run_dir) / "manifest.json")
