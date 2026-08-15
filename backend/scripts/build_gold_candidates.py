"""Generate CANDIDATE gold-label files for the evaluation harness from CUAD (feature 041, Task 8).

CUAD's expert clause-span annotations are used ONLY to SELECT candidate clauses; a documented,
heuristic risk mapping pre-fills `should_flag` / `expected_severity`. These are **CANDIDATES — NOT
independently lawyer-confirmed** (spec D4): a CUAD category is not itself a risk verdict, so every
emitted file's `notes` says the labels need human confirmation before the numbers are trusted.

The pipeline ingests PDF/DOCX only, so this selects CUAD contracts that have PDFs, copies the PDFs
into `eval/corpus/`, and writes one `eval/gold/<stem>.json` per contract in the feature-026 schema
(`load_gold`). Selection is spread across CUAD contract-type folders for diversity and is deterministic
(sorted + fixed seed).

Usage (from backend/):  python scripts/build_gold_candidates.py [--contracts 30] [--min-clauses 8]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
CUAD_ROOT = BACKEND_DIR / "data" / "kb" / "sources" / "cuad_raw" / "CUAD_v1"
CUAD_JSON = CUAD_ROOT / "CUAD_v1.json"
PDF_ROOT = CUAD_ROOT / "full_contract_pdf"
CORPUS_OUT = BACKEND_DIR / "eval" / "corpus"
GOLD_OUT = BACKEND_DIR / "eval" / "gold"

# ── Heuristic risk mapping (CANDIDATE only — NOT a lawyer verdict, spec D4) ──────────────────────
# CUAD categories that typically warrant a reviewer flag, with an indicative candidate severity.
RISK_HIGH = {
    "Uncapped Liability", "Non-Compete", "Ip Ownership Assignment", "Most Favored Nation",
    "Irrevocable Or Perpetual License", "Liquidated Damages",
}
RISK_MED = {
    "Cap On Liability", "Exclusivity", "No-Solicit Of Customers", "No-Solicit Of Employees",
    "Termination For Convenience", "Anti-Assignment", "Change Of Control", "Minimum Commitment",
    "Rofr/Rofo/Rofn", "Post-Termination Services", "Audit Rights", "Covenant Not To Sue",
    "Non-Disparagement", "Price Restrictions", "Volume Restriction", "Revenue/Profit Sharing",
    "Source Code Escrow", "Joint Ip Ownership", "Competitive Restriction Exception",
}
# Administrative / neutral categories → candidate CLEAN (should_flag=False), so precision + false-flag
# rate are measurable.
CLEAN = {
    "Governing Law", "Effective Date", "Expiration Date", "Renewal Term",
    "Notice Period To Terminate Renewal", "License Grant", "Non-Transferable License",
    "Warranty Duration", "Insurance", "Third Party Beneficiary",
}

_CATEGORY_RE = re.compile(r'related to "([^"]+)"')
_SNIPPET_CHARS = 160  # keep gold snippets short so the matcher's containment overlap can hit them

_CANDIDATE_NOTE = (
    "CANDIDATE labels auto-selected from CUAD expert annotations via a heuristic risk mapping "
    "(feature 041). NOT independently lawyer-confirmed — a human reviewer must confirm/correct "
    "should_flag and expected_severity before these numbers are treated as authoritative."
)


def _slug(category: str) -> str:
    return re.sub(r"[^\w]+", "_", category.strip().lower()).strip("_")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _label(category: str):
    """Return (should_flag, expected_severity) candidate, or None to skip an ambiguous category."""
    if category in RISK_HIGH:
        return True, "high"
    if category in RISK_MED:
        return True, "medium"
    if category in CLEAN:
        return False, None
    return None


def _contract_clauses(contract: dict) -> list[dict]:
    """Build candidate gold clauses from one CUAD contract's annotated spans."""
    clauses: list[dict] = []
    seen: set = set()
    for para in contract.get("paragraphs", []):
        for qa in para.get("qas", []):
            if qa.get("is_impossible"):
                continue
            m = _CATEGORY_RE.search(qa.get("question", ""))
            if not m:
                continue
            decision = _label(m.group(1))
            if decision is None:
                continue
            should_flag, severity = decision
            for ans in qa.get("answers", []):
                snippet = _norm(ans.get("text", ""))[:_SNIPPET_CHARS]
                key = snippet.lower()
                if len(snippet) < 40 or key in seen:
                    continue
                seen.add(key)
                clauses.append({
                    "locator": {"section_number": None, "text_snippet": snippet},
                    "should_flag": should_flag,
                    "expected_severity": severity,
                    "clause_type": _slug(m.group(1)),
                    "note": m.group(1),
                })
    return clauses


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate CANDIDATE gold files from CUAD.")
    ap.add_argument("--contracts", type=int, default=30, help="number of contracts to select")
    ap.add_argument("--min-clauses", type=int, default=8, help="min labeled clauses per contract")
    args = ap.parse_args()

    if not CUAD_JSON.exists():
        raise SystemExit(f"CUAD not found at {CUAD_JSON}. Run `python scripts/fetch_cuad.py` first.")

    data = json.loads(CUAD_JSON.read_text(encoding="utf-8"))["data"]
    by_title = {c["title"]: c for c in data}
    # Map each contract title → its PDF path (title == pdf stem for 505/510), grouped by type folder.
    pdfs_by_folder: dict = defaultdict(list)
    for pdf in sorted(PDF_ROOT.rglob("*.pdf")):
        if pdf.stem in by_title:
            pdfs_by_folder[pdf.parent.name].append(pdf)

    # Round-robin across contract-type folders for diversity; deterministic (sorted).
    ordered: list[Path] = []
    folders = sorted(pdfs_by_folder)
    i = 0
    while len(ordered) < len(by_title) and any(pdfs_by_folder.values()):
        folder = folders[i % len(folders)]
        if pdfs_by_folder[folder]:
            ordered.append(pdfs_by_folder[folder].pop(0))
        i += 1

    CORPUS_OUT.mkdir(parents=True, exist_ok=True)
    GOLD_OUT.mkdir(parents=True, exist_ok=True)

    selected = 0
    total_clauses = 0
    for pdf in ordered:
        if selected >= args.contracts:
            break
        clauses = _contract_clauses(by_title[pdf.stem])
        if len(clauses) < args.min_clauses:
            continue
        # Copy the source PDF into eval/corpus/ so the gold `document` path is self-contained.
        dest_pdf = CORPUS_OUT / pdf.name
        shutil.copyfile(pdf, dest_pdf)
        gold = {
            "document": f"eval/corpus/{pdf.name}",
            "notes": _CANDIDATE_NOTE,
            "clauses": clauses,
        }
        gold_path = GOLD_OUT / (re.sub(r"[^\w.-]+", "_", pdf.stem)[:80] + ".json")
        gold_path.write_text(json.dumps(gold, indent=2, ensure_ascii=False), encoding="utf-8")
        selected += 1
        total_clauses += len(clauses)
        print(f"  {gold_path.name}: {len(clauses)} candidate clauses")

    print(f"\nWrote {selected} candidate gold files / {total_clauses} clauses -> eval/gold/ "
          f"(+ source PDFs -> eval/corpus/). Labels are CANDIDATES — human confirmation required.")
    if selected < 25 or total_clauses < 250:
        print(f"WARNING: below the AC-6 floor (>=25 files / >=250 clauses): "
              f"got {selected}/{total_clauses}. Increase --contracts or lower --min-clauses.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
