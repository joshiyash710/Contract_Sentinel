"""Tally a human-reviewed miss-triage sheet (feature 041 follow-up to build_miss_triage.py).

Reads a `misses_*.csv` after a reviewer has filled the blank `verdict` column with `real_miss` or
`label_overflag`, and reports the split overall / by disposition / by clause_type. It then echoes the
decision-tree branch the triage plan calls for (real_miss ⇒ spec the earlier relevance-gate/Branch-B
fix; label_overflag ⇒ clean up the candidate gold labels). Pure offline — no Ollama, no app.* import.

Verdict parsing is tolerant: case / spaces / hyphens are normalized, and any value containing "real"
counts as real_miss, "overflag"/"label" as label_overflag; blanks are reported as still-to-review.

Run from backend/:
    python -X utf8 scripts/tally_miss_verdicts.py eval/runs/20260817-190549/miss_triage/misses_sample.csv
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

_REAL = "real_miss"
_OVERFLAG = "label_overflag"
_BLANK = "(blank)"

# Fraction of DECIDED rows at/above which we call a clear majority (else "mixed").
_MAJORITY = 0.60


def normalize_verdict(raw: str) -> str:
    v = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not v:
        return _BLANK
    if "real" in v:
        return _REAL
    if "overflag" in v or "over_flag" in v or "label" in v:
        return _OVERFLAG
    return f"other:{v}"


def _pct(n: int, d: int) -> str:
    return "N/A" if not d else f"{100 * n / d:.1f}%"


def _bar(counts: Counter, keys) -> str:
    return "  ".join(f"{k}={counts.get(k, 0)}" for k in keys)


def tally(csv_path: Path) -> dict:
    with csv_path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"{csv_path}: no rows")
    if "verdict" not in rows[0]:
        raise SystemExit(f"{csv_path}: no `verdict` column — is this a miss-triage sheet?")

    overall = Counter()
    by_type: dict = defaultdict(Counter)
    by_disp: dict = defaultdict(Counter)
    for r in rows:
        v = normalize_verdict(r.get("verdict", ""))
        overall[v] += 1
        by_type[r.get("clause_type", "?")][v] += 1
        by_disp[r.get("disposition", "?")][v] += 1
    return {"n": len(rows), "overall": overall, "by_type": by_type, "by_disp": by_disp}


def _recommend(overall: Counter) -> str:
    real, over = overall.get(_REAL, 0), overall.get(_OVERFLAG, 0)
    decided = real + over
    if decided == 0:
        return "No verdicts filled yet — mark rows real_miss / label_overflag, then re-run."
    rf = real / decided
    if rf >= _MAJORITY:
        return (f"Mostly REAL_MISS ({_pct(real, decided)} of decided). → The misses are genuine. "
                "Next: spec a runtime fix to the EARLIER relevance-gate / Branch-B discard "
                "(NOT the 027/ISSUP lever — discards happen before ISSUP). Needs a feature branch.")
    if (1 - rf) >= _MAJORITY:
        return (f"Mostly LABEL_OVERFLAG ({_pct(over, decided)} of decided). → Recall is ~fine; the "
                "candidate gold labels over-flag. Next: clean up eval/gold/*.json (offline, no "
                "runtime change), then re-score.")
    return (f"MIXED ({_pct(real, decided)} real / {_pct(over, decided)} overflag). → Use the "
            "by_clause_type split below to target: fix the gate for types dominated by real_miss, "
            "clean labels for types dominated by label_overflag.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Tally a reviewed miss-triage CSV (offline).")
    ap.add_argument("csv_path", help="a filled misses_*.csv from build_miss_triage.py")
    args = ap.parse_args()

    csv_path = Path(args.csv_path)
    res = tally(csv_path)
    overall, n = res["overall"], res["n"]
    decided = overall.get(_REAL, 0) + overall.get(_OVERFLAG, 0)

    print("\n" + "=" * 72)
    print(f"MISS-VERDICT TALLY — {csv_path}")
    print("=" * 72)
    print(f"rows: {n}   decided: {decided} ({_pct(decided, n)})   "
          f"still blank: {overall.get(_BLANK, 0)}")
    print("\nOverall verdicts:")
    for v, c in overall.most_common():
        print(f"  {v:16s} {c:4d}  ({_pct(c, n)})")

    other = [v for v in overall if v.startswith("other:")]
    if other:
        print(f"\n  ! unrecognized verdict values (ignored in the split): {other}")

    print("\nBy disposition (real_miss / label_overflag / blank):")
    for disp, cnt in sorted(res["by_disp"].items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {disp:22s} {_bar(cnt, (_REAL, _OVERFLAG, _BLANK))}")

    print("\nBy clause_type (decided rows only, real / overflag — sorted by real):")
    typ = sorted(
        res["by_type"].items(),
        key=lambda kv: (-kv[1].get(_REAL, 0), -kv[1].get(_OVERFLAG, 0)),
    )
    for t, cnt in typ:
        r, o, b = cnt.get(_REAL, 0), cnt.get(_OVERFLAG, 0), cnt.get(_BLANK, 0)
        if r or o:
            print(f"  {t:34s} real={r:<3d} overflag={o:<3d}" + (f"  (blank={b})" if b else ""))

    print("\n" + "-" * 72)
    print("RECOMMENDATION:")
    print("  " + _recommend(overall).replace(". ", ".\n  "))
    print("=" * 72)


if __name__ == "__main__":
    main()
