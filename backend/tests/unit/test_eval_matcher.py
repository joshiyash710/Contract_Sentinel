"""Unit tests for the eval-harness finding↔gold matcher (feature 026, AC-4 / EC-2,3).

Pure + deterministic; no Ollama, no network.
"""

from eval.harness.matcher import match, overlap
from eval.harness.schema import GoldClause


def finding(text, section=None, position=1, clause_id="c", risk="high", conf=0.9):
    return {
        "clause_id": clause_id,
        "clause_text": text,
        "section_number": section,
        "position": position,
        "risk_level": risk,
        "confidence_score": conf,
    }


def gold(snippet, section=None, should_flag=True, severity="high"):
    return GoldClause(
        section_number=section,
        text_snippet=snippet,
        should_flag=should_flag,
        expected_severity=severity,
    )


def test_overlap_containment():
    # all snippet tokens present in finding → 1.0
    assert overlap("the provider liability shall not exceed fees", "liability shall not exceed") == 1.0
    # none present → 0.0
    assert overlap("governing law of delaware", "indemnify hold harmless") == 0.0


def test_matches_by_overlap_despite_different_ids_and_positions():
    findings = [finding("In no event shall aggregate liability exceed monthly fees",
                        clause_id="c-77", position=9)]
    golds = [gold("aggregate liability exceed monthly fees", section="3.1")]
    res = match(findings, golds)
    assert len(res.matches) == 1
    assert res.matches[0][0]["clause_id"] == "c-77"
    assert res.matches[0][1] is golds[0]
    assert res.unmatched_findings == []
    assert res.unmatched_gold == []


def test_tie_break_prefers_section_number_match():
    # two gold clauses with equal text overlap; the finding's section matches the second
    f = [finding("mutual indemnification clause text here", section="5.2")]
    g_a = gold("indemnification clause text", section="9.9")
    g_b = gold("indemnification clause text", section="5.2")
    res = match(f, [g_a, g_b])
    assert len(res.matches) == 1
    assert res.matches[0][1] is g_b  # section-number tie-break wins


def test_one_to_one_no_double_count():
    f = [finding("indemnify hold harmless from all claims", clause_id="a"),
         finding("indemnify hold harmless from all claims", clause_id="b")]
    g = [gold("indemnify hold harmless")]  # should_flag True
    res = match(f, g)
    assert len(res.matches) == 1                       # gold matched once
    assert len(res.surplus_findings) == 1              # the second (over-split) is surplus…
    assert res.unmatched_findings == []                # …NOT a false-flag (EC-3)


def test_unmatched_finding_is_false_flag_candidate():
    f = [finding("this is unrelated boilerplate about notices")]
    g = [gold("limitation of liability cap", should_flag=True)]
    res = match(f, g)
    assert res.matches == []
    assert len(res.unmatched_findings) == 1            # overlaps no should_flag:true clause → FP
    assert res.surplus_findings == []
    assert len(res.unmatched_gold) == 1                # the risky gold clause is a miss
