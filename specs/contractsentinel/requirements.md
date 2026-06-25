# ContractSentinel Requirements Specification

## 1. Open Decision Resolutions

### 1.1 Target User and Demo Persona
WHEN a user uploads a contract for analysis, THE SYSTEM SHALL target freelance software developers reviewing client service agreements as the primary persona. This scope is chosen because:
- Freelance developers frequently encounter standardized but potentially risky service agreements
- The contract types are well-bounded (service agreements, NDAs, licensing terms)
- Severity calibration can be specifically tuned to risks most relevant to this persona (payment terms, IP ownership, liability exposure, termination clauses)

### 1.2 Minimum Demoable Slice
WHEN the system processes a contract, THE SYSTEM SHALL demonstrate a minimum viable path through IngestAgent → ClauseSplitterAgent → CRAGRetrievalNode → SelfRAGValidationNode → ReportAgent. This path validates the core evidence-grounded risk detection capability without requiring redline generation or MCP delivery.

### 1.3 Clause Knowledge Base Sourcing
WHEN initializing the system, THE SYSTEM SHALL source its initial knowledge base from a curated seed set of 500 clause patterns across 5 risk categories (payment terms, liability, IP rights, termination, confidentiality), manually compiled from public legal resources including:
- Standard contract templates from legal aid websites
- Published clause libraries from bar associations
- Academic legal writing on common contract pitfalls
Each pattern shall include citation metadata for traceability.

### 1.4 Definition of "Validated" for Demo Purposes
WHEN a risk finding is generated, THE SYSTEM SHALL produce an auditable validation log showing:
- The specific clause text analyzed
- The evidence source used (local KB or web fallback)
- The outcome of each Self-RAG step (Retrieve, ISREL, ISSUP, ISUSE)
- Any retry attempts and their outcomes
- The final validation decision
This log shall be accessible per finding in the final report for external verification.

## 2. Pipeline Stage Requirements

### 2.1 IngestAgent Requirements

WHEN a user uploads a PDF or DOCX file, THE SYSTEM SHALL parse the document and extract text content with 95%+ accuracy compared to original formatting.

Acceptance Criteria:
- Successfully parse standard PDF and DOCX formats
- Fall back to OCR processing for scanned documents
- Preserve document structure sufficient for clause segmentation
- Handle documents up to 100 pages in length
- Observable artifact: parsed text content with preserved section references

WHEN document parsing fails, THE SYSTEM SHALL retry the operation once before falling back to OCR processing.

Acceptance Criteria:
- Retry mechanism implemented for parsing failures
- OCR fallback activated after 2 failed parsing attempts
- Observable artifact: error log showing parsing attempts and fallback activation

### 2.2 ClauseSplitterAgent Requirements

WHEN processing parsed document text, THE SYSTEM SHALL segment the contract into individual clauses with 90%+ accuracy in identifying natural clause boundaries.

Acceptance Criteria:
- Identify clause boundaries based on section headings, numbering patterns, and punctuation
- Preserve cross-references between clauses
- Assign unique identifiers to each clause
- Maintain clause position/section metadata
- Observable artifact: list of segmented clauses with metadata

WHEN encountering ambiguous clause boundaries, THE SYSTEM SHALL err on the side of smaller, more granular segments rather than merging potentially distinct clauses.

Acceptance Criteria:
- Granular segmentation approach documented
- No clause exceeds 500 words in length
- Observable artifact: segmentation algorithm parameters

### 2.3 CRAGRetrievalNode Requirements

WHEN processing each clause, THE SYSTEM SHALL query the local vector knowledge base and obtain a confidence score for relevant evidence.

Acceptance Criteria:
- Query local FAISS vector store for each clause
- Calculate similarity/confidence score between clause and knowledge base entries
- Observable artifact: confidence score per clause

WHEN the confidence score is ≥ 0.72, THE SYSTEM SHALL use local knowledge base evidence for Self-RAG validation.

Acceptance Criteria:
- Threshold value of 0.72 applied
- Local evidence tagged as source
- Observable artifact: routing decision log showing "local" path

WHEN the confidence score is < 0.72, THE SYSTEM SHALL issue a live web search query and use the result as evidence.

Acceptance Criteria:
- Web search triggered for scores below threshold
- Web-sourced evidence tagged appropriately
- Observable artifact: routing decision log showing "web" path

WHEN web search fails or times out, THE SYSTEM SHALL proceed with local-only evidence and flag the finding as lower-confidence.

Acceptance Criteria:
- 10-second timeout for web search
- Fallback to local evidence on timeout/failure
- Confidence flag applied to findings using fallback evidence
- Observable artifact: timeout/failure log entries

### 2.4 SelfRAGValidationNode Requirements

WHEN validating a clause with retrieved evidence, THE SYSTEM SHALL execute the four-token Self-RAG sequence: Retrieve → ISREL → ISSUP → ISUSE.

Acceptance Criteria:
- Each validation step executed in sequence
- Outcome logged for each step
- Observable artifact: per-clause validation log showing all four steps

WHEN the ISREL step determines evidence is not relevant, THE SYSTEM SHALL discard the candidate finding for that clause with no retries.

Acceptance Criteria:
- Immediate discard on ISREL failure
- No retry attempts for irrelevant evidence
- Observable artifact: discard log with ISREL failure reason

WHEN the ISSUP step determines evidence does not support risk classification, THE SYSTEM SHALL discard the candidate finding.

Acceptance Criteria:
- Immediate discard on "does not support" outcome
- Observable artifact: discard log with ISSUP failure reason

WHEN the ISSUP step determines evidence partially supports risk classification, THE SYSTEM SHALL retry retrieval up to 2 times before discarding if still inconclusive.

Acceptance Criteria:
- Maximum 2 retry attempts for partial support
- Discard after 2 unsuccessful retries
- Observable artifact: retry count and outcomes in validation log

WHEN the ISUSE step determines a finding is not of sufficient practical severity, THE SYSTEM SHALL discard the candidate finding.

Acceptance Criteria:
- Discard on ISUSE failure
- Observable artifact: discard log with ISUSE failure reason

WHEN a clause passes all four Self-RAG steps, THE SYSTEM SHALL mark it as a validated finding and proceed to risk scoring.

Acceptance Criteria:
- All four steps pass successfully
- Clause added to validated findings list
- Observable artifact: validation completion log

### 2.5 RiskScoreAgent Requirements

WHEN processing validated findings, THE SYSTEM SHALL assign a severity score of low, medium, or high based on risk impact to the target user persona.

Acceptance Criteria:
- Three-tier severity classification (low/medium/high)
- Scoring algorithm tuned for freelance developer risks
- Observable artifact: severity scores assigned to validated findings

WHEN no validated findings exist, THE SYSTEM SHALL route to SkipRedline node instead of RedlineAgent.

Acceptance Criteria:
- Conditional routing based on findings count
- Empty findings list triggers SkipRedline path
- Observable artifact: routing decision log

WHEN validated findings exist, THE SYSTEM SHALL route to RedlineAgent for suggested revisions.

Acceptance Criteria:
- Non-empty findings list triggers RedlineAgent path
- Only medium/high severity findings trigger redline generation
- Observable artifact: routing decision log

### 2.6 RedlineAgent Requirements

WHEN processing medium or high severity findings, THE SYSTEM SHALL generate suggested safer language alternatives.

Acceptance Criteria:
- Redline suggestions generated for medium/high severity only
- Suggestions preserve clause intent while reducing risk
- Observable artifact: redline suggestions paired with original clauses

WHEN redline generation fails for any finding, THE SYSTEM SHALL proceed with report generation without that specific redline.

Acceptance Criteria:
- Graceful failure handling for individual redlines
- Report generation not blocked by single redline failure
- Observable artifact: error log for failed redline generation

### 2.7 ReportAgent Requirements

WHEN compiling the final report, THE SYSTEM SHALL include all validated findings with their evidence trail and validation logs.

Acceptance Criteria:
- All validated findings included
- Complete evidence trail preserved per finding
- Full Self-RAG validation logs included
- Observable artifact: structured report with all required elements

WHEN generating the report, THE SYSTEM SHALL format findings by severity and include clause context.

Acceptance Criteria:
- Findings organized by severity (high, medium, low)
- Original clause text included with each finding
- Observable artifact: formatted report structure

### 2.8 MCP Delivery Requirements

WHEN delivering the final report, THE SYSTEM SHALL save the report to Google Drive via MCP tool call.

Acceptance Criteria:
- Google Drive MCP server integration implemented
- Report saved with descriptive filename
- Observable artifact: Drive save confirmation

WHEN delivering the final report, THE SYSTEM SHALL send the report via Gmail using MCP tool call.

Acceptance Criteria:
- Gmail MCP server integration implemented
- Email sent to user with report attachment
- Observable artifact: email send confirmation

WHEN Google Drive save succeeds but Gmail send fails, THE SYSTEM SHALL retry Gmail send up to 3 times before marking delivery as partially failed.

Acceptance Criteria:
- Retry mechanism for Gmail failures
- Maximum 3 retry attempts
- Partial failure state properly recorded
- Observable artifact: retry log and final delivery status