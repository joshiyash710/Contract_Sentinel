"""Feature 055 Task 12 — extraction-diff measurement (OQ-2, gates the 057 default-flip).

Compares, per corpus PDF, the flag-ON dict-built extracted_text (page.get_text("dict") spans
concatenated per the production _extract_text_with_spans) vs the flag-OFF plain path
("\\n".join(page.get_text())). Reports char-level similarity, whitespace-collapsed similarity
(isolates pure spacing differences), length delta, and regex clause-count drift.

Offline, read-only, no app state touched. Run from backend/:
    .venv/Scripts/python.exe eval/measure_055_extraction_diff.py
"""

import sys
from difflib import SequenceMatcher
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import fitz  # pymupdf

from app.graph.nodes.parsers.pdf_parser import _extract_text_with_spans
from app.graph.nodes.splitters.regex_splitter import split_by_regex

CORPUS = BACKEND_DIR / "eval" / "corpus"


def _collapse_ws(s: str) -> str:
    return " ".join(s.split())


def main() -> int:
    pdfs = sorted(p for p in CORPUS.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"No PDFs in {CORPUS}")
        return 1

    rows = []
    for p in pdfs:
        doc = fitz.open(str(p))
        try:
            plain = "\n".join(page.get_text() for page in doc)
            dict_text, _spans = _extract_text_with_spans(doc)
        finally:
            doc.close()

        raw_ratio = SequenceMatcher(None, plain, dict_text).ratio()
        ws_ratio = SequenceMatcher(None, _collapse_ws(plain), _collapse_ws(dict_text)).ratio()
        n_plain = len(split_by_regex(plain))
        n_dict = len(split_by_regex(dict_text))
        rows.append(
            {
                "name": p.name[:50],
                "len_plain": len(plain),
                "len_dict": len(dict_text),
                "raw": raw_ratio,
                "ws": ws_ratio,
                "clauses_plain": n_plain,
                "clauses_dict": n_dict,
            }
        )

    def mean(key):
        return sum(r[key] for r in rows) / len(rows)

    def median(key):
        xs = sorted(r[key] for r in rows)
        m = len(xs) // 2
        return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2

    clause_changed = [r for r in rows if r["clauses_plain"] != r["clauses_dict"]]

    print(f"\n{'doc':50} {'raw%':>6} {'ws%':>6} {'dLen':>7} {'cl_pln':>6} {'cl_dct':>6}")
    print("-" * 90)
    for r in sorted(rows, key=lambda r: r["raw"]):
        print(
            f"{r['name']:50} {r['raw']*100:6.2f} {r['ws']*100:6.2f} "
            f"{r['len_dict']-r['len_plain']:7d} {r['clauses_plain']:6d} {r['clauses_dict']:6d}"
        )

    print("\n=== AGGREGATE (n={}) ===".format(len(rows)))
    print(f"raw char similarity : mean {mean('raw')*100:.2f}%  median {median('raw')*100:.2f}%  "
          f"min {min(r['raw'] for r in rows)*100:.2f}%")
    print(f"ws-collapsed similar: mean {mean('ws')*100:.2f}%  median {median('ws')*100:.2f}%  "
          f"min {min(r['ws'] for r in rows)*100:.2f}%")
    print(f"docs w/ clause-count change: {len(clause_changed)}/{len(rows)}")
    for r in clause_changed:
        print(f"   {r['name']:50} {r['clauses_plain']} -> {r['clauses_dict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
