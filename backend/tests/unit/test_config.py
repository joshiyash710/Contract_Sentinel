"""
Unit tests for app.config — IngestAgent threshold constants.

Written BEFORE app/config.py exists (TDD red phase).
Run: python -m pytest tests/unit/test_config.py -v
Expected before Task 4: FAIL with ModuleNotFoundError
Expected after Task 4:  PASS
"""


def test_threshold_values_match_spec():
    """Verify all IngestAgent constants match specs/003-ingest-agent/spec.md §6."""
    from app.config import (
        MIN_TEXT_LENGTH_THRESHOLD,
        MIN_CHAR_DENSITY_THRESHOLD,
        OCR_LOW_CONFIDENCE_THRESHOLD,
        INGEST_TIMEOUT_SECONDS,
    )

    assert MIN_TEXT_LENGTH_THRESHOLD == 50
    assert MIN_CHAR_DENSITY_THRESHOLD == 100
    assert OCR_LOW_CONFIDENCE_THRESHOLD == 0.6
    assert INGEST_TIMEOUT_SECONDS == 60


def test_thresholds_are_correct_types():
    """Verify threshold types: int for counts, float for ratios, int for seconds."""
    from app.config import (
        MIN_TEXT_LENGTH_THRESHOLD,
        MIN_CHAR_DENSITY_THRESHOLD,
        OCR_LOW_CONFIDENCE_THRESHOLD,
        INGEST_TIMEOUT_SECONDS,
    )

    assert isinstance(MIN_TEXT_LENGTH_THRESHOLD, int)
    assert isinstance(MIN_CHAR_DENSITY_THRESHOLD, int)
    assert isinstance(OCR_LOW_CONFIDENCE_THRESHOLD, float)
    assert isinstance(INGEST_TIMEOUT_SECONDS, int)


def test_clause_splitter_constants_match_spec():
    """Verify ClauseSplitterAgent constants match specs/004 §6."""
    from app.config import (
        OLLAMA_MODEL_NAME,
        CLAUSE_SPLITTER_TIMEOUT_SECONDS,
        MIN_CLAUSE_LENGTH,
        MAX_CLAUSES_LIMIT,
    )

    assert OLLAMA_MODEL_NAME == "qwen3:14b"
    assert CLAUSE_SPLITTER_TIMEOUT_SECONDS == 120
    assert MIN_CLAUSE_LENGTH == 100
    assert MAX_CLAUSES_LIMIT == 500


def test_clause_splitter_constants_correct_types():
    """Verify types: str for model name, int for timeout/length/limit."""
    from app.config import (
        OLLAMA_MODEL_NAME,
        CLAUSE_SPLITTER_TIMEOUT_SECONDS,
        MIN_CLAUSE_LENGTH,
        MAX_CLAUSES_LIMIT,
    )

    assert isinstance(OLLAMA_MODEL_NAME, str)
    assert isinstance(CLAUSE_SPLITTER_TIMEOUT_SECONDS, int)
    assert isinstance(MIN_CLAUSE_LENGTH, int)
    assert isinstance(MAX_CLAUSES_LIMIT, int)


def test_crag_runtime_constants_match_spec():
    """Verify CRAG runtime constants match specs/005 §6."""
    from app.config import (
        CRAG_TOP_K,
        CRAG_WEB_MAX_RESULTS,
        CRAG_MAX_EVIDENCE_SNIPPETS,
        CRAG_QUERY_MAX_CHARS,
        CRAG_EMBED_TIMEOUT_SECONDS,
        CRAG_WEB_TIMEOUT_SECONDS,
        CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD,
    )
    assert CRAG_TOP_K == 5
    assert CRAG_WEB_MAX_RESULTS == 5
    assert CRAG_MAX_EVIDENCE_SNIPPETS == 5
    assert CRAG_QUERY_MAX_CHARS == 2000
    assert CRAG_EMBED_TIMEOUT_SECONDS == 30
    assert CRAG_WEB_TIMEOUT_SECONDS == 20
    assert CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD == 5


def test_crag_constants_correct_types():
    """Verify types: int counts/timeouts, float threshold, str model/paths."""
    from app import config
    assert isinstance(config.CRAG_TOP_K, int)
    assert isinstance(config.CRAG_WEB_MAX_RESULTS, int)
    assert isinstance(config.CRAG_MAX_EVIDENCE_SNIPPETS, int)
    assert isinstance(config.CRAG_QUERY_MAX_CHARS, int)
    assert isinstance(config.CRAG_EMBED_TIMEOUT_SECONDS, int)
    assert isinstance(config.CRAG_WEB_TIMEOUT_SECONDS, int)
    assert isinstance(config.CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD, int)
    assert isinstance(config.CRAG_CONFIDENCE_THRESHOLD, float)
    assert isinstance(config.OLLAMA_EMBED_MODEL_NAME, str)
    assert isinstance(config.CRAG_KB_INDEX_PATH, str)
    assert isinstance(config.CRAG_KB_METADATA_PATH, str)


def test_embed_model_distinct_from_generative():
    """Constitution §8 model-separation rule (AC-8): embedding model must not
    equal the generative model."""
    from app.config import OLLAMA_EMBED_MODEL_NAME, OLLAMA_MODEL_NAME
    assert OLLAMA_EMBED_MODEL_NAME != OLLAMA_MODEL_NAME
    assert OLLAMA_EMBED_MODEL_NAME == "bge-m3"
