"""
Shared pytest markers for ContractSentinel tests.

Single source of truth — import from here rather than defining markers
inline in individual test files or in conftest.py, which is not reliably
importable as a package module in all pytest configurations.

Usage:
    from tests.markers import requires_tesseract
"""
import shutil

import pytest

requires_tesseract = pytest.mark.skipif(
    not shutil.which("tesseract"),
    reason="Tesseract OCR is not installed",
)
