"""Unit tests for the feature-042 deterministic clause-type fallback tagger.

Pure, offline (no Ollama). Covers AC-1 (correctness + conservative negatives),
AC-2/EC-1 (multi-match tie-break), EC-2 (empty text), and AC-6 (determinism).
"""

import app.graph.nodes.splitters.clause_typer as clause_typer
from app.graph.nodes.splitters.clause_typer import infer_clause_type
from app.graph.state import ClauseType


# ── AC-1 positives ──────────────────────────────────────────────────────────
def test_liability_snippet():
    text = (
        "Limitation of Liability. In no event shall either party be liable for any "
        "consequential damages arising out of this Agreement."
    )
    assert infer_clause_type(text) == ClauseType.LIABILITY


def test_indemnification_is_liability():
    text = (
        "The Vendor shall indemnify and hold harmless the Customer against all claims, "
        "losses and damages arising from a breach of this Agreement."
    )
    assert infer_clause_type(text) == ClauseType.LIABILITY


def test_termination_snippet():
    text = (
        "Either party may terminate this Agreement upon thirty (30) days written notice. "
        "The confidentiality obligations shall survive termination."
    )
    assert infer_clause_type(text) == ClauseType.TERMINATION


def test_intellectual_property_snippet():
    text = (
        "The Contractor hereby assigns to the Company all right, title and interest in and "
        "to the intellectual property created under this Agreement, including any work product."
    )
    assert infer_clause_type(text) == ClauseType.INTELLECTUAL_PROPERTY


def test_confidentiality_snippet():
    text = (
        "The Receiving Party shall not disclose any Confidential Information of the Disclosing "
        "Party and shall keep confidential all proprietary information."
    )
    assert infer_clause_type(text) == ClauseType.CONFIDENTIALITY


# ── AC-1 negatives (lock in the conservative map) ───────────────────────────
def test_neutral_boilerplate_is_none():
    text = (
        "Notices. All notices under this Agreement shall be in writing and delivered to the "
        "addresses set forth on the signature page."
    )
    assert infer_clause_type(text) is None


def test_passing_ip_words_do_not_match():
    """A definitions/representation clause merely MENTIONING patent/copyright/trademark in
    passing must NOT be typed intellectual_property (no bare single words in the map, D3)."""
    text = (
        '"Marks" means the patent, copyright and trademark registrations owned by a party '
        "as listed in Schedule A for informational purposes only."
    )
    assert infer_clause_type(text) is None


def test_anti_assignment_is_not_ip():
    """Anti-assignment boilerplate must NOT match intellectual_property (no generic
    'assignment of' fragment in the map, D3)."""
    text = (
        "No assignment of this Agreement or any rights hereunder may be made by either party "
        "without the prior written consent of the other party."
    )
    assert infer_clause_type(text) is None


# ── AC-2 / EC-1 tie-break; EC-2 empty text ──────────────────────────────────
def test_multi_match_resolves_by_map_order():
    """A clause with both confidentiality and liability language resolves to the type that
    comes first in the ordered map (confidentiality precedes liability by default)."""
    text = (
        "The Receiving Party shall not disclose any Confidential Information; in no event shall "
        "the Disclosing Party be liable for consequential damages."
    )
    assert infer_clause_type(text) == ClauseType.CONFIDENTIALITY


def test_empty_and_whitespace_and_none_are_none():
    assert infer_clause_type("") is None
    assert infer_clause_type("   \n\t ") is None
    assert infer_clause_type(None) is None


# ── AC-6 determinism ─────────────────────────────────────────────────────────
def test_repeated_calls_are_identical():
    text = "Limitation of liability applies; in no event shall a party be liable."
    first = infer_clause_type(text)
    for _ in range(5):
        assert infer_clause_type(text) == first


def test_reads_module_map_so_patching_changes_result(monkeypatch):
    """Proves the tagger reads the module-level map (no hidden constant): swapping in a
    custom map changes the result deterministically."""
    text = "This clause mentions a widget and nothing else legal."
    assert infer_clause_type(text) is None  # no match under default map

    monkeypatch.setattr(
        clause_typer,
        "DETERMINISTIC_CLAUSE_TYPE_PATTERNS",
        (("liability", ("widget",)),),
    )
    assert infer_clause_type(text) == ClauseType.LIABILITY
