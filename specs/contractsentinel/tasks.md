# ContractSentinel Implementation Tasks

## 1. Project Setup and Foundation

1. Set up Python project structure with FastAPI backend framework
   - Satisfies: IngestAgent requirements (pipeline foundation)
   - Dependencies: FastAPI, LangGraph, FAISS, document parsing libraries

2. Configure local Ollama integration for Qwen3 model execution
   - Satisfies: All LLM-dependent requirements
   - Implement model calling wrapper with retry logic for structured output

3. Implement ContractState data model and persistence layer using SQLite
   - Satisfies: Shared state requirements, persistence requirements
   - Create SQLite schema for job/user/report metadata

## 2. Document Ingestion Pipeline

4. Implement IngestAgent for PDF/DOCX parsing with OCR fallback
   - Satisfies: IngestAgent requirements
   - Integrate PDF/DOCX parsing libraries
   - Implement OCR fallback using Tesseract or similar

5. Implement ClauseSplitterAgent for contract segmentation
   - Satisfies: ClauseSplitterAgent requirements
   - Develop algorithm for identifying clause boundaries
   - Preserve cross-references and section metadata

## 3. Knowledge Base and Retrieval System

6. Set up FAISS vector store for local clause knowledge base
   - Satisfies: CRAGRetrievalNode requirements
   - Implement embedding generation for clauses
   - Create FAISS index structure

7. Curate initial seed knowledge base of 500 clause patterns
   - Satisfies: Clause knowledge base sourcing requirement
   - Compile patterns from public legal resources
   - Structure data with metadata for traceability

8. Implement CRAGRetrievalNode with confidence-based routing
   - Satisfies: CRAGRetrievalNode requirements
   - Integrate local KB lookup with FAISS
   - Implement web search fallback integration
   - Add confidence scoring and threshold logic (0.72)

## 4. Evidence Validation Pipeline (Minimum Demoable Slice)

9. **[MINIMUM DEMOABLE SLICE MILESTONE]** Implement SelfRAGValidationNode core logic
   - Satisfies: SelfRAGValidationNode requirements, minimum demoable slice
   - Implement Retrieve → ISREL → ISSUP → ISUSE sequence
   - Add retry logic for ISSUP partial support outcomes
   - Create validation logging per clause

10. Implement RiskScoreAgent for severity classification
    - Satisfies: RiskScoreAgent requirements
    - Develop scoring algorithm for freelance developer risks
    - Implement severity classification (low/medium/high)

11. Implement conditional routing logic for risk-based path selection
    - Satisfies: Risk routing conditional edge requirements
    - Create route_on_risk function
    - Implement SkipRedline node for clean contracts

12. Implement ReportAgent for structured report generation
    - Satisfies: ReportAgent requirements
    - Create report template with findings, evidence, validation logs
    - Format output for human readability

## 5. Advanced Features

13. Implement RedlineAgent for suggested safer language
    - Satisfies: RedlineAgent requirements
    - Develop redline generation for medium/high severity findings
    - Implement graceful failure handling for individual redlines

14. Set up Google Drive MCP server integration
    - Satisfies: MCP delivery requirements
    - Implement MCP resource operations for file saving
    - Add retry logic for connection timeouts

15. Set up Gmail MCP server integration
    - Satisfies: MCP delivery requirements
    - Implement MCP resource operations for email sending
    - Add retry logic and partial failure handling

16. Implement complete MCP delivery with failure recovery
    - Satisfies: MCP delivery requirements
    - Integrate Drive and Gmail delivery
    - Implement partial failure handling (Drive success but Gmail failure)

## 6. Quality Assurance and Testing

17. Create test suite for Self-RAG validation with auditable logs
    - Satisfies: Definition of "validated" requirement
    - Implement validation log inspection capabilities
    - Create test cases for each Self-RAG step outcome

18. Implement end-to-end integration tests for minimum demoable slice
    - Satisfies: Minimum demoable slice requirement
    - Test complete path: ingest → split → CRAG → SelfRAG → report
    - Validate evidence trail and validation logs

19. Conduct performance testing with 100-page contracts
    - Satisfies: Document processing requirements
    - Verify processing within reasonable time bounds
    - Test OCR fallback performance

20. Document system operation and validation log interpretation
    - Satisfies: Auditable log requirements
    - Create user guide for interpreting validation evidence
    - Document system limitations and confidence indicators

## 7. Deployment and Documentation

21. Create deployment scripts for local execution environment
    - Satisfies: Execution environment constraints
    - Package dependencies for Ollama/Qwen3 setup
    - Document setup procedure for demo environment

22. Prepare IEEE publication documentation on evidence-grounded detection
    - Satisfies: Academic publication requirements
    - Document Self-RAG implementation with legal clause KB
    - Prepare performance metrics and validation methodology