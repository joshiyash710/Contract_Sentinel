"""Feature 053 (AC-2/AC-3): the container entrypoint runs the Turso-aware migration (not the bare
alembic CLI, which uses the wrong URL on Turso), and the Dockerfile ships the KB index."""

from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]


def test_entrypoint_is_turso_aware():
    txt = (_BACKEND / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "upgrade_to_head" in txt, "entrypoint must call the Turso-aware upgrade_to_head"
    assert "alembic upgrade head" not in txt, "entrypoint must NOT use the bare alembic CLI (wrong URL on Turso)"


def test_dockerfile_ships_kb_index():
    txt = (_BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY data/kb" in txt, "Dockerfile must COPY data/kb so CRAG resolves the FAISS index in the image"


def test_dockerignore_keeps_kb_index():
    """The Dockerfile COPYs data/kb; .dockerignore must not strip it from the build context (feature 053).

    A `data/` exclusion silently drops data/kb from the context → `COPY data/kb` fails at build.
    """
    di = (_BACKEND / ".dockerignore").read_text(encoding="utf-8")
    if "data/" in di:  # some form of data exclusion present
        assert "!data/kb" in di, ".dockerignore excludes data/ but does not re-include data/kb"

