"""
Offline corpus-curation utility for the CRAG local clause knowledge base.

Reads the curated source documents in ``app/db/*.md`` (Bonterms Cloud Terms and
DPA) and emits a JSONL of reference clauses — one object per line, each with
exactly ``snippet_text`` and ``source_reference`` — which is the input format
that ``build_kb.py`` embeds into the FAISS index (specs/005-crag-retrieval §7.3).

This script performs *data curation only*: no embeddings, no FAISS. It is
deterministic and re-runnable; running it again fully rewrites the corpus file.

Usage (from the backend/ directory):

    python scripts/build_corpus.py
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

# ── Paths (anchored to backend/, the pipeline's working directory) ─────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BACKEND_DIR / "app" / "db"
CORPUS_PATH = BACKEND_DIR / "data" / "kb" / "clauses_corpus.jsonl"

# Each source doc: filename -> human-readable citation prefix for source_reference.
SOURCES = {
    "Cloud-Terms.md": "Bonterms Cloud Terms (v1.0)",
    "Data-Protection-Addendum.md": "Bonterms DPA (v1.0)",
}

# A numbered (sub)section header, bold or plain, e.g.
#   **1. The Agreement**.        -> "1"    title "The Agreement"
#   **5.1.** Use of Customer Data. -> "5.1" title "Use of Customer Data"
#   **5.3**.                     -> "5.3"
#   1.7.  "**Data Protection...   -> "1.7"  (DPA plain-numbered subsections)
#   2.1.  Roles of the Parties.  -> "2.1"  title "Roles of the Parties"
_HEADER_RE = re.compile(
    r"^\*{0,2}(?P<num>\d+(?:\.\d+)?)\.?\*{0,2}\.?\s+(?P<rest>.*)$"
)

# A defined-term entry in an (unnumbered) Definitions section, e.g.
#   "**Cloud Service**" means ...
_DEFINITION_RE = re.compile(r'^"\*\*(?P<term>[^*]+)\*\*"')

# Minimum length for a paragraph to stand alone as its own clause snippet.
_MIN_SNIPPET_CHARS = 40


def _strip_markdown(text: str) -> str:
    """Remove bold markers and collapse whitespace for clean embedding input."""
    text = text.replace("**", "").replace("<br />", " ").replace("<br/>", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _read_paragraphs(md_path: Path) -> List[str]:
    """Split a markdown file into non-empty, stripped paragraphs (blank-line sep)."""
    raw = md_path.read_text(encoding="utf-8")
    # Drop the leading H1 title line and the trailing license/footer block.
    lines = [ln for ln in raw.splitlines() if not ln.startswith("# ")]
    blob = "\n".join(lines)
    paras = [p.strip() for p in re.split(r"\n\s*\n", blob) if p.strip()]
    return paras


@dataclass
class _Clause:
    number: Optional[str]  # e.g. "5.1", or None for an unnumbered definition
    title: str
    body_parts: List[str]

    def text(self) -> str:
        joined = " ".join(part for part in self.body_parts if part)
        return _strip_markdown(joined)


def _is_footer(para: str) -> bool:
    low = para.lower()
    return (
        "free to use under" in low
        or "does not provide legal advice" in low
        or low.startswith("©")
        or low.startswith("learn more")
    )


def _parse_document(md_path: Path, citation: str) -> Iterator[dict]:
    """Yield corpus records for one source document."""
    paras = _read_paragraphs(md_path)
    current: Optional[_Clause] = None

    def flush(clause: Optional[_Clause]) -> Iterator[dict]:
        if clause is None:
            return
        snippet = clause.text()
        if len(snippet) < _MIN_SNIPPET_CHARS:
            return
        if clause.number:
            ref = f"{citation} §{clause.number}"
            if clause.title:
                ref += f" — {clause.title}"
        else:
            ref = f"{citation} §Definitions — {clause.title}"
        yield {"snippet_text": snippet, "source_reference": ref}

    for para in paras:
        if _is_footer(para):
            continue

        # A markdown table row (DPA Schedules list) is not a clause.
        if para.lstrip().startswith("|"):
            continue

        def_match = _DEFINITION_RE.match(para)
        header_match = _HEADER_RE.match(para)

        if def_match:
            # Standalone defined-term entry (Cloud Terms §23 style).
            yield from flush(current)
            term = def_match.group("term").strip()
            current = _Clause(number=None, title=term, body_parts=[para])
            continue

        if header_match:
            num = header_match.group("num")
            rest = header_match.group("rest").strip()
            # Derive a short title: leading "Sentence case." fragment if present.
            title = ""
            body = rest
            m = re.match(r"([A-Z][^.]{0,60}?)\.\s+(.*)$", rest)
            if m and not m.group(1).endswith(","):
                title = _strip_markdown(m.group(1))
                body = m.group(2)
            elif rest and len(rest) < 60 and rest.endswith("."):
                title = _strip_markdown(rest.rstrip("."))
                body = ""
            yield from flush(current)
            current = _Clause(number=num, title=title, body_parts=[body] if body else [])
            continue

        # Continuation paragraph — belongs to the current clause.
        if current is not None:
            current.body_parts.append(para)

    yield from flush(current)


def main() -> None:
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    records: List[dict] = []
    for filename, citation in SOURCES.items():
        md_path = DB_DIR / filename
        if not md_path.exists():
            raise FileNotFoundError(f"Source document not found: {md_path}")
        doc_records = list(_parse_document(md_path, citation))
        print(f"  {filename}: {len(doc_records)} clauses")
        records.extend(doc_records)

    with CORPUS_PATH.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Wrote {len(records)} reference clauses -> {CORPUS_PATH.relative_to(BACKEND_DIR)}")


if __name__ == "__main__":
    main()
