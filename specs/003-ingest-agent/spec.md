# IngestAgent Specification

## 1. Problem Statement

The IngestAgent is Node 1 of the fixed 7-node pipeline defined in `specs/000-constitution.md`. Its primary responsibility is to parse uploaded contracts (PDF or DOCX format) into clean extracted text that can be consumed by the ClauseSplitterAgent (Node 2).

This node serves as the entry point for all document processing in the ContractSentinel pipeline. It handles both direct text extraction from digital documents and OCR-based extraction for scanned documents, ensuring that downstream nodes receive properly formatted text regardless of the input document's nature.

## 2. Inputs and Outputs

### Inputs
The IngestAgent accepts a single document with the following constraints:
- `document_path`: Path to the document file (string)
- Format must be PDF or DOCX (other formats should be rejected with a clear error state)
- File must be accessible and readable

### Outputs
The IngestAgent populates the following fields in the ContractState (as defined in `specs/001-contract-state-schema.md`):

**Fields populated by IngestAgent:**
- `document_id`: Unique identifier for the document (string)
- `document_path`: Path to the raw document file (string)
- `original_filename`: Original filename of the uploaded document (string)
- `uploaded_at`: ISO timestamp when the document was uploaded (string)
- `extracted_text`: Full extracted text from the document (string)
- `ocr_used`: Boolean indicating whether OCR was needed for extraction (boolean)
- `ocr_confidence`: OCR confidence score if OCR was used, otherwise None (Optional[float])

All other fields in the ContractState remain at their default values and are populated by subsequent nodes in the pipeline.

## 3. Acceptance Criteria

1. **Format Validation**: The agent must accept only PDF and DOCX files, rejecting all other formats with a clear error state by setting `ingest_error` with `error_type: "unsupported_format"`.

2. **Direct Text Extraction**: For digital documents, the agent must first attempt direct text extraction without OCR.

3. **OCR Fallback - Empty Text**: Given extracted text under MIN_TEXT_LENGTH_THRESHOLD (50 characters), the agent MUST set `ocr_used=True` and attempt OCR extraction.

4. **OCR Fallback - Low Density**: Given extracted text with character density below MIN_CHAR_DENSITY_THRESHOLD (100 characters per page) but above MIN_TEXT_LENGTH_THRESHOLD, the agent MUST set `ocr_used=True` and attempt OCR extraction.

5. **OCR Confidence Handling**: When OCR is used, the agent must:
   - Capture the OCR confidence score
   - Continue processing even with low confidence scores
   - Store the confidence score in the state for downstream consumption
   - If OCR confidence falls below OCR_LOW_CONFIDENCE_THRESHOLD (0.6), processing continues but the document should be flaggable downstream as low-confidence

6. **State Population**: The agent must correctly populate all required fields in the ContractState, including generating document_id via `uuid.uuid4()`.

7. **Error Handling**: The agent must handle corrupted files, permission issues, and timeouts with clear error states stored in the `ingest_error` field with appropriate error_type values.

8. **No Clause Processing**: The agent must not produce any clause-level output (reserved for ClauseSplitterAgent).

9. **Timeout Handling**: The agent must complete processing within INGEST_TIMEOUT_SECONDS (60 seconds) or set `ingest_error` with `error_type: "timeout"`.

10. **Pipeline Short-Circuit**: When `ingest_error` is populated, the graph's routing logic must short-circuit the pipeline rather than passing empty/garbage extracted_text to ClauseSplitterAgent.

## 4. Edge Cases

1. **Unsupported File Formats**: Files with extensions other than .pdf or .docx/.docx should be rejected with `ingest_error` set to `{"error_type": "unsupported_format", "message": "..."}`.

2. **Empty Documents**: Documents that contain text under MIN_TEXT_LENGTH_THRESHOLD (50 characters) after direct extraction, triggering unconditional OCR fallback.

3. **Low Character Density Documents**: Documents with character density below MIN_CHAR_DENSITY_THRESHOLD (100 characters per page) but above the empty threshold, triggering OCR fallback.

4. **OCR Low Confidence**: OCR processing that produces confidence scores below OCR_LOW_CONFIDENCE_THRESHOLD (0.6), which continues processing but flags the document for downstream consumers.

5. **Corrupted Files**: Files with correct extensions but corrupted content that cannot be parsed, resulting in `ingest_error` with `error_type: "corrupted_file"`.

6. **Permission Issues**: Files that cannot be accessed due to permission restrictions, resulting in `ingest_error` with `error_type: "permission_denied"`.

7. **Large Files**: Documents that exceed system memory or processing capabilities (handled through timeout mechanisms).

8. **Timeout Conditions**: Processing that exceeds INGEST_TIMEOUT_SECONDS (60 seconds), resulting in `ingest_error` with `error_type: "timeout"`.

9. **Character Density Calculation**: Character density is calculated as `len(extracted_text) / page_count` using page count from the parsing library's own metadata (PyMuPDF for PDF, python-docx for DOCX).

## 5. Out of Scope

The IngestAgent does NOT handle:
1. **Clause Splitting**: This is the responsibility of ClauseSplitterAgent (Node 2)
2. **Content Analysis**: Any semantic analysis or understanding of the extracted text
3. **Privacy Processing**: Any redaction or privacy filtering (reserved for Phase 2 PrivacyAgent)
4. **Format Conversion**: Converting between document formats beyond extraction
5. **Document Validation**: Verifying the legal validity or completeness of contracts
6. **Metadata Extraction**: Extracting document metadata beyond basic file information
7. **Batch Processing**: Processing multiple documents simultaneously

Any functionality related to these areas should be implemented in subsequent nodes or future phases.

## 6. Configurable Constants

The following named constants must be defined in a shared config module per the constitution's configurable-thresholds rule:

```python
MIN_TEXT_LENGTH_THRESHOLD = 50  # characters; below this, text is "empty"
MIN_CHAR_DENSITY_THRESHOLD = 100  # characters per page; below this but above empty threshold, OCR triggers
OCR_LOW_CONFIDENCE_THRESHOLD = 0.6  # normalized 0-1 scale for OCR confidence scores
INGEST_TIMEOUT_SECONDS = 60  # per-document processing timeout
```

## 7. Evaluation

When OCR is used, the following metrics should be logged for later analysis:

1. **OCR Confidence Distribution**: Histogram of confidence scores across processed documents
2. **OCR Usage Rate**: Percentage of documents requiring OCR vs. direct extraction
3. **OCR Failure Rate**: Percentage of documents where OCR confidence falls below OCR_LOW_CONFIDENCE_THRESHOLD (0.6)
4. **Processing Time**: Time taken for direct extraction vs. OCR processing
5. **Character Density Analysis**: Distribution of character-to-page ratios for documents requiring OCR fallback
6. **Format Success Rates**: Success rates by document format (PDF vs DOCX)

These metrics will help optimize the OCR thresholds and identify patterns in document processing requirements.

## 8. Resolved Questions

All previously open questions have been resolved with the following decisions:

1. **OCR Confidence Thresholds**: RESOLVED - Defined as named constants in a shared config module:
   - `MIN_TEXT_LENGTH_THRESHOLD = 50` (characters)
   - `MIN_CHAR_DENSITY_THRESHOLD = 100` (characters per page)
   - `OCR_LOW_CONFIDENCE_THRESHOLD = 0.6` (normalized 0-1 scale)
   - `INGEST_TIMEOUT_SECONDS = 60` (per-document processing timeout)

2. **Near-Empty Text Definition**: RESOLVED - Defined as text under `MIN_TEXT_LENGTH_THRESHOLD` (50 characters).

3. **Document ID Generation**: RESOLVED - Generated via `uuid.uuid4()`, cast to string.

4. **Error State Representation**: RESOLVED - Added `ingest_error: Optional[Dict[str, str]]` field to ContractState with error_type values: "unsupported_format", "corrupted_file", "permission_denied", "timeout".

5. **Character Density Calculation**: RESOLVED - Calculated as `len(extracted_text) / page_count` using page count from the parsing library's own metadata.

6. **Timeout Handling**: RESOLVED - Processing timeout set to `INGEST_TIMEOUT_SECONDS = 60` seconds with timeout errors stored in `ingest_error`.