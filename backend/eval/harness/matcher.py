"""Finding ↔ gold-clause matching for the evaluation harness (feature 026, §2.4 / §3.3).

Deterministic, one-to-one, overlap-based. Pure (imports only config + schema); no app.*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from eval.harness.config import EVAL_MATCH_MIN_OVERLAP
from eval.harness.schema import GoldClause

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize(s: Optional[str]) -> List[str]:
    """Lowercase → alphanumeric tokens (drops punctuation/whitespace)."""
    return _TOKEN_RE.findall((s or "").lower())


def overlap(finding_text: Optional[str], snippet: Optional[str]) -> float:
    """Containment of the gold snippet within the finding text, in [0, 1].

    The gold snippet is (usually) a fragment of the clause, so we measure how much of it appears
    in the finding — |tokens(snippet) ∩ tokens(finding)| / |tokens(snippet)|.
    """
    snip = set(normalize(snippet))
    if not snip:
        return 0.0
    found = set(normalize(finding_text))
    return len(snip & found) / len(snip)


@dataclass
class MatchResult:
    matches: List[Tuple[dict, GoldClause]] = field(default_factory=list)
    unmatched_findings: List[dict] = field(default_factory=list)  # → false-flag candidates
    surplus_findings: List[dict] = field(default_factory=list)  # dropped (EC-3)
    unmatched_gold: List[GoldClause] = field(default_factory=list)


def _section_match(finding: dict, g: GoldClause) -> bool:
    fs, gs = finding.get("section_number"), g.section_number
    return fs is not None and gs is not None and str(fs) == str(gs)


def match(findings: List[dict], gold: List[GoldClause]) -> MatchResult:
    """Greedy best-first one-to-one matching (≥ EVAL_MATCH_MIN_OVERLAP)."""
    # All candidate pairs above threshold.
    pairs = []
    for fi, f in enumerate(findings):
        for gi, g in enumerate(gold):
            ov = overlap(f.get("clause_text"), g.text_snippet)
            if ov >= EVAL_MATCH_MIN_OVERLAP:
                pairs.append((ov, _section_match(f, g), fi, gi))
    # Sort: highest overlap, then section-number match, then stable by indices.
    pairs.sort(key=lambda p: (p[0], p[1], -p[2], -p[3]), reverse=True)

    used_f: set = set()
    used_g: set = set()
    res = MatchResult()
    for ov, _sec, fi, gi in pairs:
        if fi in used_f or gi in used_g:
            continue
        used_f.add(fi)
        used_g.add(gi)
        res.matches.append((findings[fi], gold[gi]))

    # Leftover findings: surplus (overlaps an already-matched should_flag:true clause) vs false-flag.
    matched_risky_gi = {gi for gi in used_g if gold[gi].should_flag}
    for fi, f in enumerate(findings):
        if fi in used_f:
            continue
        is_surplus = any(
            overlap(f.get("clause_text"), gold[gi].text_snippet) >= EVAL_MATCH_MIN_OVERLAP
            for gi in matched_risky_gi
        )
        (res.surplus_findings if is_surplus else res.unmatched_findings).append(f)

    res.unmatched_gold = [g for gi, g in enumerate(gold) if gi not in used_g]
    return res
