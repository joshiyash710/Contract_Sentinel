"""Boundary check (feature 026 AC-10): the runtime app must NOT depend on the eval harness.

The eval harness imports app.*, never the reverse — keeps eval/ strictly offline tooling and the
runtime pipeline unaware of it (constitution §2).
"""

import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[1].parent / "app"  # backend/app
_IMPORT_EVAL = re.compile(r"^\s*(from|import)\s+eval(\.|\s|$)", re.MULTILINE)


def test_no_app_module_imports_eval():
    offenders = []
    for py in _APP.rglob("*.py"):
        if _IMPORT_EVAL.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(_APP.parent)))
    assert not offenders, f"app/ files must not import the eval harness: {offenders}"
