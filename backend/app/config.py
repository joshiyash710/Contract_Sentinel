"""
Shared configurable constants for ContractSentinel pipeline nodes.

All threshold values referenced by node logic must be defined here as named
constants — never hardcoded inline in any node — per
specs/000-constitution.md §3 (Configurable Thresholds Rule).

Future nodes (CRAG, Self-RAG, etc.) will add their own constants here.
"""

# ── IngestAgent thresholds ─────────────────────────────────────────────────────
# Source: specs/003-ingest-agent/spec.md §6
MIN_TEXT_LENGTH_THRESHOLD: int = 50  # chars; below → force OCR
MIN_CHAR_DENSITY_THRESHOLD: int = 100  # chars/page; below → force OCR
OCR_LOW_CONFIDENCE_THRESHOLD: float = (
    0.6  # normalised 0–1; below → flaggable downstream
)
INGEST_TIMEOUT_SECONDS: int = 60  # wall-clock seconds for parse_pdf / parse_docx

# ── CRAG thresholds ───────────────────────────────────────────────────────────
# Placeholder — will be populated by specs/005-crag-retrieval plan
CRAG_CONFIDENCE_THRESHOLD: float = (
    0.73  # retrieval confidence split per constitution §2
)

# ── Self-RAG thresholds ───────────────────────────────────────────────────────
# Placeholder — will be populated by specs/006-self-rag-validation plan
SELF_RAG_MAX_RETRIES: int = 3  # max retry attempts per clause per constitution §2
