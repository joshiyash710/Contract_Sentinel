# Contract State Schema

## 1. Overview

This document defines the single shared data shape flowing through the 7 Phase 1 nodes of the ContractSentinel pipeline. The state object evolves progressively as each node adds its outputs while preserving previous node results. This is the standard LangGraph StateGraph convention that enables checkpointing and recovery at any pipeline stage.

Note that Phase 2 (PrivacyAgent) will require a breaking update to this exact spec later, by design, and that this is expected, not an oversight.

## 2. Revision Note

This version corrects two major structural issues in the state schema:
1. All reducer declarations are now properly specified using Annotated types with explicit reducer functions
2. Five separate per-clause dictionaries have been consolidated into a single clauses dictionary keyed by clause_id

These changes were made per the constitution's spec-first change rule, ensuring that the specification accurately reflects the intended behavior before any implementation code is written.

## 3. Full TypedDict Definition

```python
from typing import TypedDict, List, Optional, Dict, Any, Annotated
from enum import Enum
import operator

def merge_dicts(left: dict, right: dict) -> dict:
    """Merge two dictionaries, with right taking precedence over left."""
    result = left.copy() if left else {}
    if right:
        result.update(right)
    return result

def merge_nested_clause_dicts(left: dict, right: dict) -> dict:
    """Merge nested clause dictionaries, preserving existing clause data."""
    result = left.copy() if left else {}
    if right:
        for clause_id, clause_data in right.items():
            if clause_id in result:
                # Merge the clause data, with new data taking precedence
                result[clause_id] = {**result[clause_id], **clause_data}
            else:
                result[clause_id] = clause_data
    return result

class ClauseType(str, Enum):
    DEFINITIONS = "definitions"
    PAYMENT = "payment"
    DELIVERY = "delivery"
    TERM = "term"
    TERMINATION = "termination"
    CONFIDENTIALITY = "confidentiality"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    LIABILITY = "liability"
    FORCE_MAJEURE = "force_majeure"
    DISPUTE_RESOLUTION = "dispute_resolution"
    GENERAL = "general"
    OTHER = "other"

class RetrievalPath(str, Enum):
    LOCAL_KB = "local_kb"
    WEB_FALLBACK = "web_fallback"

class ValidationStatus(str, Enum):
    DISCARDED = "discarded"
    VALIDATED = "validated"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class MCPDeliveryStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"

class MCPDeliveryInfo(TypedDict):
    status: MCPDeliveryStatus
    error_message: Optional[str]
    delivered_at: Optional[str]  # ISO timestamp

class ContractState(TypedDict):
    # Added by IngestAgent
    document_id: str
    document_path: str  # Raw document reference (file path or ID)
    original_filename: str  # Original filename of the uploaded document
    uploaded_at: str  # ISO timestamp when document was uploaded
    extracted_text: str  # Full extracted text from document
    ocr_used: bool  # Whether OCR was needed for extraction
    ocr_confidence: Optional[float]  # OCR confidence score if OCR was used
    ingest_error: Optional[Dict[str, str]]  # Error information if ingestion failed
    
    # Consolidated clause information (added progressively by different nodes)
    clauses: Annotated[Dict[str, Dict[str, Any]], merge_nested_clause_dicts]
    # Each clause record contains:
    #   text: str
    #   position: int  # Position in document (1-indexed)
    #   section_number: Optional[str]  # e.g., "1.2", "Article 5"
    #   clause_type: Optional[ClauseType]  # If inferred
    #   confidence_score: Optional[float]  # Retrieval confidence score
    #   path_taken: Optional[RetrievalPath]  # Which retrieval path was used
    #   evidence_snippets: Optional[List[Dict[str, Any]]]  # Retrieved evidence:
    #     snippet_text: str
    #     source_reference: str  # Reference to evidence source
    #   relevance_verdict: Optional[bool]  # Relevance check result
    #   isrel_verdict: Optional[bool]  # ISREL check result
    #   issup_verdict: Optional[bool]  # ISSUP check result
    #   retry_count: Optional[int]  # Number of retries attempted
    #   final_status: Optional[ValidationStatus]  # Discarded or Validated
    #   risk_level: Optional[RiskLevel]  # Low/Medium/High risk level
    #   risk_rationale: Optional[str]  # Explanation for risk level assignment
    #   suggested_rewrite: Optional[str]  # New text if risk found, None if clean
    
    # Added by ReportAgent
    report_path: Optional[str]  # Path to final report file
    evidence_trail: Annotated[List[Dict[str, Any]], operator.add]  # Evidence trail for auditability:
    #   clause_id: str
    #   evidence_source: str  # Which source supported which verdict
    #   evidence_text: str  # The supporting evidence
    #   retrieved_at: str  # ISO timestamp when evidence was retrieved/validated
    
    # Added by MCP delivery step
    mcp_delivery_status: Annotated[Dict[str, MCPDeliveryInfo], merge_dicts]  # Service -> delivery info
    
    # Pipeline-level metadata
    current_node: str  # Name of currently executing node
    error_count: Annotated[int, operator.add]  # Number of errors encountered
    retry_budgets: Annotated[Dict[str, int], merge_dicts]  # Node -> remaining retry attempts
    node_timings: Annotated[Dict[str, float], merge_dicts]  # Node -> seconds elapsed
    processing_started_at: str  # ISO timestamp
    processing_completed_at: Optional[str] # ISO timestamp
```

## 4. LangGraph Reducers

Fields that use LangGraph reducers (accumulate values):
- `clauses` - Dict that accumulates per-clause information using merge_nested_clause_dicts reducer
- `evidence_trail` - List that accumulates evidence entries using operator.add
- `error_count` - Integer that increments with each error using operator.add
- `retry_budgets` - Dict that decrements with each retry attempt using merge_dicts
- `node_timings` - Dict that accumulates node execution times using merge_dicts
- `mcp_delivery_status` - Dict that accumulates delivery status information using merge_dicts

Fields that are simple overwrites:
- `document_id`, `document_path`, `original_filename`, `uploaded_at`, `extracted_text`, `ocr_used`, `ocr_confidence`, `ingest_error`
- `report_path`
- `current_node`
- `processing_started_at`, `processing_completed_at`

Note: `ingest_error` is a simple overwrite, not an accumulating field. A new ingest attempt (e.g. on retry) fully replaces any prior error state rather than merging with it — there is no scenario where multiple ingest errors for the same document should be preserved simultaneously.

## 5. Node Implementation Guidance

When implementing a node that needs to update clause information, the node should return a partial update dict containing only the clauses key with the updated clause data. For example:

```python
# To update clause "1.2" with retrieval results:
return {
    "clauses": {
        "1.2": {
            "confidence_score": 0.85,
            "path_taken": "local_kb",
            "evidence_snippets": [
                {
                    "snippet_text": "Relevant legal text...",
                    "source_reference": "legal_doc_001"
                }
            ]
        }
    }
}

# To update clause "1.3" with validation results
# (ISSUP passed after one retry → VALIDATED):
return {
    "clauses": {
        "1.3": {
            "relevance_verdict": True,
            "isrel_verdict": True,
            "issup_verdict": True,
            "retry_count": 1,
            "final_status": ValidationStatus.VALIDATED
        }
    }
}
```

The merge_nested_clause_dicts reducer will ensure that existing clause data is preserved while new fields are added or existing fields are updated. Nodes should never include fields they haven't modified in their return values to avoid unnecessary overwrites.

## 6. Open Questions

Based on the revision, the following decisions have been made for the open questions from the previous version:

1. ~~Should we include clause length or word count as part of the clause metadata for potential downstream processing optimizations?~~
   **DECISION**: Do NOT add as a field; it's derivable from text directly, no need to store redundantly.

2. ~~Is the clause_type enumeration comprehensive enough for real-world contracts, or do we need additional categories?~~
   **DECISION**: Keep as-is for now; OTHER is a sufficient escape hatch until real sample contracts reveal gaps.

3. ~~For the evidence_trail structure, should we include timestamps for when each piece of evidence was retrieved/validated?~~
   **DECISION**: ADD a "retrieved_at" or "validated_at" ISO timestamp field to each evidence_trail entry.

4. ~~Should we track processing time per node in the pipeline-level metadata for performance monitoring?~~
   **DECISION**: ADD a new pipeline-level metadata field, node_timings: Dict[str, float], mapping node name to seconds elapsed.

5. ~~Do we need to include document metadata (filename, upload timestamp, etc.) in the state schema?~~
   **DECISION**: ADD original_filename: str and uploaded_at: str (ISO timestamp) to the fields added by IngestAgent.

6. ~~Should the MCP delivery status include more detailed information such as delivery timestamps or error messages?~~
   **DECISION**: Expand mcp_delivery_status entries to include an optional error_message: Optional[str] and a delivered_at: Optional[str] (ISO timestamp) per service.

7. ~~Is the current structure for storing OCR metadata sufficient, or do we need additional details about the OCR process?~~
   **DECISION**: Keep as-is for now; ocr_used + ocr_confidence is sufficient until a real scanned contract reveals the need for more granular detail.

8. ~~Ingest Error Field Addition~~
   **DECISION**: Added `ingest_error` field to track ingestion failures. This field is populated by IngestAgent when encountering unsupported formats, corrupted files, permission failures, or timeouts. The addition was made per the constitution's spec-first-change rule as specified in specs/003-ingest-agent/spec.md. Classified as a simple overwrite field in section 4 — see the note there.

No remaining open questions. This spec is considered final.