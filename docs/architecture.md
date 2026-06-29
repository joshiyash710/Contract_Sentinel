# ContractSentinel Architecture

This document provides an overview of the ContractSentinel system architecture, following the fixed 7-node LangGraph structure defined in the project constitution.

## Overview

ContractSentinel is an autonomous contract-risk-analysis agent built using LangGraph. The system processes legal contracts through a sequential pipeline of specialized agents, each responsible for a specific aspect of contract analysis.

## Pipeline Architecture

The system follows a fixed 7-node architecture with 2 conditional edges:

1. **IngestAgent** - Handles document parsing
2. **ClauseSplitterAgent** - Segments documents into clauses
3. **CRAG Retrieval** - Retrieves relevant legal information
4. **Self-RAG Validation** - Validates findings
5. **RiskScoreAgent** - Assigns risk levels
6. **Conditional Routing** - Routes to redlining or skip
7. **ReportAgent** - Generates final reports

## Data Flow

All components share a single evolving state object that accumulates information as it progresses through the pipeline. This state is defined in `specs/001-contract-state-schema.md`.

## System Components

### Backend Services

- **LangGraph Pipeline** - Core processing engine
- **RAG System** - Local knowledge base and web search integration
- **LLM Integration** - Qwen3 model interfaces
- **MCP Connectors** - Google Drive and Gmail integration points

### Frontend Application

- **UI Framework** - TBD (to be implemented by frontend team)
- **Dashboard** - Progress tracking and result visualization
- **Report Viewer** - Final report presentation

## Security & Privacy

Phase 1 focuses on core functionality. Security and privacy features are planned for Phase 2 implementation.

## Deployment

The system is designed to run as a standalone service with optional API access for integration with other systems.

## Future Enhancements

Refer to the constitution document for details on Phase 2 features and permanently excluded items.