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
