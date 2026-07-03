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
# Source: specs/005-crag-retrieval/spec.md §6
# NOTE: Only the constants required by the offline KB build utility
# (scripts/build_kb.py) are populated here so far. The remaining CRAG constants
# (CRAG_TOP_K, timeouts, circuit breaker, etc.) belong to the Node 3 runtime
# implementation and will be added when specs/005 is implemented.
CRAG_CONFIDENCE_THRESHOLD: float = (
    0.73  # retrieval confidence split per constitution §2
)

OLLAMA_EMBED_MODEL_NAME: str = "bge-m3"
# The Ollama EMBEDDING model — distinct from OLLAMA_MODEL_NAME (generative Qwen3)
# per constitution §8 (model-separation rule). MUST NEVER be set equal to
# OLLAMA_MODEL_NAME or used for generation. Serves CRAG (and future Self-RAG)
# clause/query embedding only.

CRAG_KB_INDEX_PATH: str = "data/kb/clauses.faiss"
# Filesystem path to the prebuilt FAISS index for the local clause KB.
# Relative to the backend/ directory (the pipeline's working directory).

CRAG_KB_METADATA_PATH: str = "data/kb/clauses_meta.jsonl"
# Sidecar mapping each FAISS vector row -> {snippet_text, source_reference}.
# Row order is 1:1 with vector IDs in the index. Same backend/-relative anchor.

# ── Self-RAG thresholds ───────────────────────────────────────────────────────
# Placeholder — will be populated by specs/006-self-rag-validation plan
SELF_RAG_MAX_RETRIES: int = 3  # max retry attempts per clause per constitution §2
