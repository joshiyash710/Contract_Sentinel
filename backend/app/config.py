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

# ── ClauseSplitterAgent thresholds ─────────────────────────────────────────────
# Source: specs/004-clause-splitter-agent/spec.md §6

OLLAMA_MODEL_NAME: str = "qwen3:14b"
# The Ollama model identifier for LLM calls in the pipeline.
# Qwen3 14B runs locally via Ollama — no cloud API cost.
# Fits in ~10GB VRAM at Q4_K_M quantization (any 12–16GB GPU).
# Used by ClauseSplitterAgent for semantic refinement and clause_type inference.
# Future nodes (CRAG, Self-RAG, etc.) may also use this constant.

CLAUSE_SPLITTER_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for the LLM call in ClauseSplitterAgent.
# Conservative starting value — Qwen3 14B is fast on GPU but needs headroom
# for long contracts and CPU-only hardware. On timeout, fall back to
# regex-only output. Benchmark on first real integration test and tune down.

MIN_CLAUSE_LENGTH: int = 100
# Minimum character count for extracted_text to be worth splitting.
# Documents shorter than this are treated as a single clause.

MAX_CLAUSES_LIMIT: int = 500
# Maximum number of clauses the node will produce.
# Documents exceeding this are truncated with a logged warning.
# Safety valve against pathological regex matches on unusual formatting.

# ── CRAG thresholds ───────────────────────────────────────────────────────────
# Placeholder — will be populated by specs/005-crag-retrieval plan
CRAG_CONFIDENCE_THRESHOLD: float = (
    0.73  # retrieval confidence split per constitution §2
)

# ── Self-RAG thresholds ───────────────────────────────────────────────────────
# Placeholder — will be populated by specs/006-self-rag-validation plan
SELF_RAG_MAX_RETRIES: int = 3  # max retry attempts per clause per constitution §2
