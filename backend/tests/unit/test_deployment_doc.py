"""Feature 053 (AC-5): docs/DEPLOYMENT.md is the Render + Turso runbook (not Oracle), documents the
mandatory pinned secrets + data-loss, the /api/health keep-alive, and the go-live checklist."""

from pathlib import Path

_DOC = Path(__file__).resolve().parents[3] / "docs" / "DEPLOYMENT.md"


def _text():
    return _DOC.read_text(encoding="utf-8")


def test_names_render_and_turso():
    txt = _text()
    assert "Render" in txt and "Turso" in txt


def test_active_plan_is_render_not_oracle():
    # The doc's title/first heading names Render (Oracle may appear only in a superseded note).
    first_heading = next(ln for ln in _text().splitlines() if ln.startswith("#"))
    assert "Render" in first_heading and "Oracle" not in first_heading


def test_pinned_secrets_data_loss_and_health():
    txt = _text()
    assert "AUTH_SECRET" in txt
    assert "CONTRACTSENTINEL_ENCRYPTION_KEY" in txt
    assert "pin" in txt.lower()  # mandatory-pinning context
    assert "/api/health" in txt  # keep-alive target


def test_go_live_checklist_names_deferred_validations():
    txt = _text()
    for token in ("050", "051", "052", "Dockerfile"):
        assert token in txt, f"go-live checklist should name {token}"
