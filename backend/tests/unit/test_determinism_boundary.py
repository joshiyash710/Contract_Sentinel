"""Feature 028 boundary guard (AC-2): the determinism sampling options are applied to exactly the
four generative Ollama chat() sites and nowhere else, and the embedding call is left untouched.

Pure source scan — no Ollama, no imports of the runtime graph.
"""

import pathlib

_NODES = pathlib.Path(__file__).resolve().parents[2] / "app" / "graph" / "nodes"

_GENERATIVE = {"llm_refiner.py", "reflectors.py", "risk_scorer.py", "redline_drafter.py"}


def test_exactly_four_generative_chat_sites_carry_sampling():
    """Only the four known generative nodes call client.chat(, and each threads temperature."""
    chat_files = [
        p for p in _NODES.rglob("*.py") if "client.chat(" in p.read_text(encoding="utf-8")
    ]
    assert {p.name for p in chat_files} == _GENERATIVE
    for p in chat_files:
        src = p.read_text(encoding="utf-8")
        assert '"temperature": OLLAMA_TEMPERATURE' in src, f"{p.name} missing sampling temperature"


def test_embeddings_call_left_untouched():
    """The BGE-M3 embedding call takes no sampling options (constitution §8, spec §2.1/AC-2)."""
    emb = (_NODES / "retrievers" / "embeddings.py").read_text(encoding="utf-8")
    assert "client.embeddings(" in emb
    assert "OLLAMA_TEMPERATURE" not in emb
    assert "OLLAMA_SEED" not in emb
