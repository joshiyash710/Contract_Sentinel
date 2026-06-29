# Tech Stack Specification

## 1. Overview

The ContractSentinel backend is built on a carefully selected set of dependencies that align with the fixed 7-node LangGraph architecture defined in the constitution. Every dependency serves a specific node or architectural layer, adhering to the principle of minimalism and clear responsibility boundaries.

All dependencies are self-hostable where practical, avoiding new paid API dependencies beyond what's already decided (Ollama for LLM serving). The stack strictly follows the model-separation rule established in the constitution, ensuring distinct separation between the generative Qwen3 models and the embedding model.

## 2. Python Version and Environment

**Target Version**: Python 3.11

**Rationale**: LangGraph's current release line requires Python 3.10+, and Python 3.11 represents the optimal middle ground considering compatibility with FAISS, OCR libraries, and other core dependencies. It provides a good balance between modern language features and ecosystem stability.

**Virtual Environment Setup**:
```bash
python3.11 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
```

## 3. Dependency Groups

### a) Core Orchestration (serves all 7 nodes' graph wiring)

- `langgraph` - Core library for implementing the 7-node state machine
- `langgraph-checkpoint-sqlite` - SQLite-based checkpointing for graph state persistence
- `langchain-core` - Core abstractions and utilities for LangChain components

**Rationale**: These packages provide the foundational orchestration layer for the entire 7-node pipeline. Note that we specifically avoid the full `langchain` package since the project requires low-level control over each of the 7 fixed nodes rather than using pre-built agent architectures.

### b) LLM + Embeddings (serves the model-separation rule in 000, point 8)

- `ollama` (Python client) - Client library for interacting with locally hosted Ollama models
- `langchain-ollama` - LangChain integration components for Ollama
- `httpx` - Modern HTTP client for API interactions

**Rationale**: These packages enable interaction with the Qwen3 models via Ollama while maintaining the strict separation between generative models (Qwen3 480B/30B) and embedding models. A dedicated embedding model (BGE-M3) is used and must never be the same model object as the generative Qwen3 models.

### c) Retrieval (serves CRAG retrieval, node 3)

- `faiss-cpu` - Vector similarity search library for local clause knowledge base
- `numpy` - Numerical computing foundation for vector operations

**Web Search Fallback**: `duckduckgo-search` - Free web search library for the "Live legal search" path when CRAG confidence < 0.73

**Rationale**: FAISS provides efficient vector search without GPU requirements, making it suitable for local deployment. The CPU version is chosen since no GPU infrastructure is assumed. DuckDuckGo search offers a free alternative to paid search APIs, though with some limitations in result quality and reliability compared to commercial options. Acceptable tradeoff for Phase 1; revisit only if testing reveals real reliability problems.

### d) Document Parsing (serves IngestAgent, node 1)

- `pymupdf` (PyMuPDF) - PDF parsing and text extraction with OCR capabilities
- `python-docx` - DOCX document parsing
- `pytesseract` - Python wrapper for Tesseract OCR engine

**System-level dependency**: Tesseract OCR engine - Required for OCR functionality, must be installed separately:
- Ubuntu/Debian: `apt-get install tesseract-ocr`
- macOS: `brew install tesseract`
- Windows: Download installer from the [official Tesseract website](https://github.com/tesseract-ocr/tesseract)

**Rationale**: These libraries provide comprehensive document parsing capabilities for the IngestAgent node, handling both text extraction and OCR fallback scenarios as specified in the architecture.

### e) Backend API Layer

- `fastapi` - Modern, high-performance web framework for building APIs
- `uvicorn` - ASGI server for running FastAPI applications
- `sse-starlette` - Server-Sent Events support for progress streaming

**Rationale**: FastAPI provides excellent performance and automatic API documentation. Uvicorn serves as the production-ready ASGI server. SSE-Starlette enables progress streaming to support the UI requirements noted in the constitution's local-model-latency consideration, since Qwen responses are slower than a hosted API and need a transport that handles long-lived connections gracefully.

### f) Database / Storage

- `sqlite3` (Python standard library) - Built-in SQLite support
- `aiosqlite` - Async driver for SQLite to work with FastAPI's async architecture
- `alembic` - Database migration tool

**Rationale**: SQLite is chosen over Postgres for Phase 1 scope due to its simplicity, zero-configuration requirements, and adequacy for the expected data volume — no multi-user production deployment is in scope. Revisit if Phase 2 deployment scope changes. Aiosqlite provides async support needed for FastAPI, and Alembic handles schema migrations.

### g) MCP Servers (Drive + Gmail only, per 000's PERMANENTLY CUT list)

- `mcp` - Official Model Context Protocol Python SDK
- `google-auth` - Google OAuth authentication library
- `google-auth-oauthlib` - OAuth 2.0 flow implementation for Google services
- `google-auth-httplib2` - HTTP transport adapter for Google authentication
- `google-api-python-client` - Google APIs client library

**Rationale**: These packages enable integration with Google Drive and Gmail services via the Model Context Protocol, as specified in the PERMANENTLY CUT section which explicitly limits MCP integrations to Drive and Gmail only.

**Version ceiling note**: The MCP Python SDK is approaching a v2 release (beta expected late June 2026, stable v2 expected roughly a month later). Official SDK guidance recommends a `<2.0.0` upper bound to avoid an unplanned breaking upgrade. This ceiling must be revisited once v2 stabilizes and the team has evaluated the migration path.

### h) Testing (serves 000's testing philosophy, point 7 — TDD)

- `pytest` - Testing framework
- `pytest-asyncio` - Async support for pytest
- `pytest-cov` - Coverage reporting plugin
- `pytest-mock` - Mocking framework integration

**Rationale**: Pytest provides a robust testing foundation that aligns with the TDD philosophy. The async plugin supports testing of FastAPI and MCP async code, while coverage reporting ensures comprehensive test coverage.

### i) Evaluation Tooling (serves the Evaluation sections that 005-crag-retrieval and 006-self-rag-validation specs will require)

- `pandas` - Data analysis and manipulation for evaluation results
- `scikit-learn` - Machine learning utilities for computing precision/recall metrics
- `matplotlib` - Visualization of evaluation results
- `seaborn` - Statistical data visualization

**Rationale**: These libraries provide the necessary tools for organizing evaluation results and computing precision/recall-style metrics from logged eval data as required by future evaluation specifications.

### j) Dev Tooling

- `black` - Code formatter
- `ruff` - Fast Python linter
- `mypy` - Static type checker

**Rationale**: Black ensures consistent code formatting. Ruff provides fast linting with a wide range of checks. MyPy aligns with the constitution's TypedDict/Pydantic convention (point 4), providing static type checking that complements the runtime validation offered by Pydantic for API boundaries.

## 4. Full pyproject.toml Dependency Block

```toml
[project]
name = "contractsentinel"
version = "0.1.0"
description = "Autonomous contract-risk-analysis agent"
authors = [{ name = "Yash Joshi", email = "yash@example.com" }]
readme = "README.md"
requires-python = ">=3.11,<3.12"
dependencies = [
    "langgraph>=1.2.0,<2.0.0",
    "langgraph-checkpoint-sqlite>=0.1.0",
    "langchain-core>=0.3.0",
    "ollama>=0.3.0",
    "langchain-ollama>=1.1.0,<2.0.0",
    "httpx>=0.27.0",
    "faiss-cpu>=1.8.0",
    "numpy>=1.24.0",
    "duckduckgo-search>=6.0.0",
    "pymupdf>=1.23.0",
    "python-docx>=1.1.0",
    "pytesseract>=0.3.10",
    "fastapi>=0.110.0",
    "uvicorn>=0.29.0",
    "sse-starlette>=2.0.0",
    "aiosqlite>=0.20.0",
    "alembic>=1.13.0",
    "mcp>=1.27,<2.0.0",
    "google-auth>=2.29.0",
    "google-auth-oauthlib>=1.2.0",
    "google-auth-httplib2>=0.2.0",
    "google-api-python-client>=2.125.0",
    "pydantic>=2.7.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "pytest-mock>=3.12.0",
    "black>=24.0.0",
    "ruff>=0.4.0",
    "mypy>=1.9.0",
]
eval = [
    "pandas>=2.2.0",
    "scikit-learn>=1.4.0",
    "matplotlib>=3.8.0",
    "seaborn>=0.13.0",
]

[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"
```

## 5. Explicitly Excluded

1. **Full `langchain` package** - Not used since the project needs low-level control over each of the 7 fixed nodes, not a pre-built agent architecture.
2. **`faiss-gpu`** - Excluded in favor of `faiss-cpu` since no GPU infrastructure is assumed.
3. **Paid search APIs (Google Custom Search, Bing Search, etc.)** - Excluded in favor of the free `duckduckgo-search` library for web search fallback.
4. **PostgreSQL and related drivers** - Excluded in favor of SQLite for Phase 1 scope simplicity.
5. **Dedicated KMS/Vault key management libraries** - Excluded per the PERMANENTLY CUT list.
6. **Slack, Notion, or other MCP integration libraries** - Excluded per the PERMANENTLY CUT list which limits MCP to Drive + Gmail only.
7. **RBAC/granular permissions libraries** - Excluded per the PERMANENTLY CUT list.
8. **Compliance-certification libraries** - Excluded per the PERMANENTLY CUT list.
9. **Flake8** - Excluded in favor of Ruff which is faster and more comprehensive.

## 6. Open Questions

All open questions from the initial draft have been resolved:

1. ~~**Embedding Model Choice**~~ — **RESOLVED**: BGE-M3, for simplicity alongside the existing Qwen3 480B/30B Ollama setup, well-established performance, and no current need for legal-domain-specific embedding tuning.

2. ~~**Web Search Fallback**~~ — **RESOLVED**: `duckduckgo-search` for Phase 1, with the reliability tradeoff accepted for a non-production build; revisit only if testing reveals real problems.

3. ~~**Version Pinning**~~ — **RESOLVED**: `langgraph`, `mcp`, and `langchain-ollama` version floors have been corrected against verified current PyPI releases at the time of writing this spec. These three were specifically checked because they are the fastest-moving packages in this stack; the remaining packages' floors are considered low-risk as written.

4. ~~**Tesseract Installation**~~ — **RESOLVED**: Explicit OS-specific install commands added to section 3d.

5. ~~**Build Backend**~~ — **RESOLVED**: Confirmed setuptools, as shown in section 4, not Poetry.

