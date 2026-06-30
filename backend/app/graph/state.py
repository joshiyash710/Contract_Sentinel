"""
ContractSentinel pipeline state schema.

This is a verbatim transcription of specs/001-contract-state-schema.md §3.
Do NOT modify this file without first updating that spec per
specs/000-constitution.md §10 (Spec-First Change Rule).
"""

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
    evidence_trail: Annotated[List[Dict[str, Any]], operator.add]  # Evidence trail:
    #   clause_id: str
    #   evidence_source: str  # Which source supported which verdict
    #   evidence_text: str  # The supporting evidence
    #   retrieved_at: str  # ISO timestamp when evidence was retrieved/validated

    # Added by MCP delivery step
    mcp_delivery_status: Annotated[
        Dict[str, MCPDeliveryInfo], merge_dicts
    ]  # Service -> delivery info

    # Pipeline-level metadata
    current_node: str  # Name of currently executing node
    error_count: Annotated[int, operator.add]  # Number of errors encountered
    retry_budgets: Annotated[
        Dict[str, int], merge_dicts
    ]  # Node -> remaining retry attempts
    node_timings: Annotated[Dict[str, float], merge_dicts]  # Node -> seconds elapsed
    processing_started_at: str  # ISO timestamp
    processing_completed_at: Optional[str]  # ISO timestamp
