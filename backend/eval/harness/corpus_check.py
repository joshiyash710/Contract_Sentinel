"""Pure corpus-record validation + loading for the CRAG KB build (feature 041).

Shared by `scripts/build_kb.py` — so the additive-metadata preservation is the SAME code the unit
test exercises — and by `tests/unit/test_corpus_shape.py`. Imports nothing from `app.*` and no
faiss/ollama, so it stays offline and unit-testable (AC-2).

The corpus records (`data/kb/clauses_corpus.jsonl`) require exactly two keys — `snippet_text` and
`source_reference`; feature-041 sources (CUAD/EDGAR) may additionally carry the optional string keys
below. `build_kb` writes the FULL record to `clauses_meta.jsonl`, so preserving these keys here is
what makes the eval's per-clause-type analysis possible. Additive keys are OPTIONAL — a source that
omits them leaves the key ABSENT (never present-but-null).
"""

from __future__ import annotations

import json
from typing import Iterable, List

REQUIRED_KEYS = ("snippet_text", "source_reference")
# Optional additive metadata carried through to clauses_meta.jsonl (041). When present, each must be a
# non-empty string; absent (not null) when the source omits it.
OPTIONAL_STR_KEYS = ("clause_type", "source_license", "jurisdiction")


class CorpusError(ValueError):
    """Raised when a corpus record violates the required/additive-key contract."""


def validate_corpus(records: Iterable[dict]) -> None:
    """Validate corpus records. Raises CorpusError on the first violation."""
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise CorpusError(f"record[{i}] is not an object: {rec!r}")
        for k in REQUIRED_KEYS:
            v = rec.get(k)
            if not isinstance(v, str) or not v.strip():
                raise CorpusError(f"record[{i}] missing/empty required key {k!r}")
        for k in OPTIONAL_STR_KEYS:
            if k in rec:
                v = rec[k]
                if v is None:
                    raise CorpusError(
                        f"record[{i}] key {k!r} is null; omit the key rather than storing null"
                    )
                if not isinstance(v, str) or not v.strip():
                    raise CorpusError(
                        f"record[{i}] key {k!r} must be a non-empty string, got {v!r}"
                    )


def load_corpus_records(text: str) -> List[dict]:
    """Parse a clauses_corpus.jsonl blob into full records, requiring the two mandatory keys and
    PRESERVING every other key (additive metadata). Blank lines are skipped. This is exactly the set
    of records build_kb writes to clauses_meta.jsonl — so additive keys survive the build."""
    records: List[dict] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        for k in REQUIRED_KEYS:
            if not rec.get(k):
                raise CorpusError(f"corpus line {line_no} missing required key {k!r}: {rec!r}")
        records.append(rec)  # preserve ALL keys (additive metadata — 041)
    return records
