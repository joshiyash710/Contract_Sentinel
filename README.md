# ContractSentinel

An autonomous contract-risk-analysis agent built with LangGraph.

## Overview

ContractSentinel is an AI-powered system that automatically analyzes legal contracts to identify potential risks and suggest improvements. The system processes contracts through a multi-stage pipeline that extracts clauses, retrieves relevant legal information, validates findings, and generates detailed reports with recommended redlines.

## Architecture

The system follows a fixed 7-node LangGraph architecture:

1. **IngestAgent** - Parses PDF/DOCX contracts with OCR fallback
2. **ClauseSplitterAgent** - Segments documents into discrete clauses
3. **CRAG Retrieval** - Retrieves relevant legal information using confidence-rated retrieval
4. **Self-RAG Validation** - Validates findings with relevance and support checks
5. **RiskScoreAgent** - Assigns risk levels to validated findings
6. **Conditional Routing** - Routes to redlining or skip based on risk
7. **ReportAgent** - Compiles final reports with evidence trails

## Development Approach

This project follows a strict spec-driven development workflow:

1. Create specification (`specs/00X-feature-name/spec.md`)
2. Create technical plan (`specs/00X-feature-name/plan.md`)
3. Create implementation tasks (`specs/00X-feature-name/tasks.md`)
4. Implementation

All development must follow the rules defined in `specs/000-constitution.md`.

## Project Structure

```
contractsentinel/
├── CLAUDE.md
├── .claude/
│   ├── settings.json
│   └── commands/
├── specs/
│   ├── 000-constitution.md
│   └── 001-contract-state-schema.md
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   └── app/
│       ├── graph/
│       ├── rag/
│       ├── mcp_servers/
│       ├── llm/
│       ├── api/
│       ├── models/
│       └── db/
├── frontend/
│   ├── package.json
│   └── src/
└── docs/
```

## Getting Started

1. Install dependencies with Poetry:
   ```
   cd backend
   poetry install
   ```

2. Set up environment variables:
   ```
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. Follow the spec-driven workflow to implement features:
   - Check existing specs in the `specs/` directory
   - Create new feature specs following the template in `.claude/commands/spec.md`

## Team

- Yash Joshi - Backend Implementation
- Bansi - Frontend Implementation

## Documentation

- [Architecture](docs/architecture.md)
- [Constitution (Rules & Constraints)](specs/000-constitution.md)
- [State Schema](specs/001-contract-state-schema.md)