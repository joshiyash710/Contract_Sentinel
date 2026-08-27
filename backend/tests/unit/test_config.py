"""
Unit tests for app.config — IngestAgent threshold constants.

Written BEFORE app/config.py exists (TDD red phase).
Run: python -m pytest tests/unit/test_config.py -v
Expected before Task 4: FAIL with ModuleNotFoundError
Expected after Task 4:  PASS
"""


def test_threshold_values_match_spec():
    """Verify all IngestAgent constants match specs/003-ingest-agent/spec.md §6."""
    from app.config import (
        MIN_TEXT_LENGTH_THRESHOLD,
        MIN_CHAR_DENSITY_THRESHOLD,
        OCR_LOW_CONFIDENCE_THRESHOLD,
        INGEST_TIMEOUT_SECONDS,
    )

    assert MIN_TEXT_LENGTH_THRESHOLD == 50
    assert MIN_CHAR_DENSITY_THRESHOLD == 100
    assert OCR_LOW_CONFIDENCE_THRESHOLD == 0.6
    assert INGEST_TIMEOUT_SECONDS == 60


def test_thresholds_are_correct_types():
    """Verify threshold types: int for counts, float for ratios, int for seconds."""
    from app.config import (
        MIN_TEXT_LENGTH_THRESHOLD,
        MIN_CHAR_DENSITY_THRESHOLD,
        OCR_LOW_CONFIDENCE_THRESHOLD,
        INGEST_TIMEOUT_SECONDS,
    )

    assert isinstance(MIN_TEXT_LENGTH_THRESHOLD, int)
    assert isinstance(MIN_CHAR_DENSITY_THRESHOLD, int)
    assert isinstance(OCR_LOW_CONFIDENCE_THRESHOLD, float)
    assert isinstance(INGEST_TIMEOUT_SECONDS, int)


def test_clause_splitter_constants_match_spec():
    """Verify ClauseSplitterAgent constants match specs/004 §6."""
    from app.config import (
        OLLAMA_MODEL_NAME,
        CLAUSE_SPLITTER_TIMEOUT_SECONDS,
        MIN_CLAUSE_LENGTH,
        MAX_CLAUSES_LIMIT,
        CLAUSE_SPLITTER_LLM_MAX_CLAUSES,
    )

    assert OLLAMA_MODEL_NAME == "qwen3:8b"
    assert CLAUSE_SPLITTER_TIMEOUT_SECONDS == 120
    assert MIN_CLAUSE_LENGTH == 100
    assert MAX_CLAUSES_LIMIT == 500
    assert CLAUSE_SPLITTER_LLM_MAX_CLAUSES == 40  # feature 025 latency lever A (§3)


def test_clause_splitter_constants_correct_types():
    """Verify types: str for model name, int for timeout/length/limit."""
    from app.config import (
        OLLAMA_MODEL_NAME,
        CLAUSE_SPLITTER_TIMEOUT_SECONDS,
        MIN_CLAUSE_LENGTH,
        MAX_CLAUSES_LIMIT,
    )

    assert isinstance(OLLAMA_MODEL_NAME, str)
    assert isinstance(CLAUSE_SPLITTER_TIMEOUT_SECONDS, int)
    assert isinstance(MIN_CLAUSE_LENGTH, int)
    assert isinstance(MAX_CLAUSES_LIMIT, int)


def test_clause_splitter_lever_f_constants_match_spec():
    """Feature 029 Lever F (§3): slim-refinement toggle + output-token cap (AC-18)."""
    from app.config import (
        CLAUSE_SPLITTER_LLM_EMIT_TEXT,
        CLAUSE_SPLITTER_LLM_NUM_PREDICT,
    )

    assert CLAUSE_SPLITTER_LLM_EMIT_TEXT is False  # default: grouping mode, no text re-emit
    assert CLAUSE_SPLITTER_LLM_NUM_PREDICT == 4096  # feature 047: raised 1024→4096 (large-doc grouping)


def test_clause_splitter_lever_f_constants_correct_types():
    """bool toggle, int token cap (AC-18)."""
    from app import config

    assert isinstance(config.CLAUSE_SPLITTER_LLM_EMIT_TEXT, bool)
    assert isinstance(config.CLAUSE_SPLITTER_LLM_NUM_PREDICT, int)


def test_clause_splitter_tolerant_grouping_flag_is_bool():
    """Feature 047 (§3): tolerant-grouping toggle, bool type (AC-5). Shipped default False after AC-10
    (no measured recall gain; mechanism proven but target case token-capped) — see 047 RESULTS.md."""
    from app import config

    assert isinstance(config.CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING, bool)
    assert config.CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING is False


def test_ollama_sampling_constants_match_spec():
    """Verify determinism constants match specs/028 §2.1 (AC-1)."""
    from app.config import OLLAMA_TEMPERATURE, OLLAMA_SEED

    assert OLLAMA_TEMPERATURE == 0.0  # greedy decode, product-wide (028 D1)
    assert OLLAMA_SEED == 42  # fixed seed for reproducibility (028 D7)


def test_ollama_sampling_constants_correct_types():
    """Verify types: float temperature, int (Optional[int]) seed (AC-1)."""
    from app.config import OLLAMA_TEMPERATURE, OLLAMA_SEED

    assert isinstance(OLLAMA_TEMPERATURE, float)
    assert isinstance(
        OLLAMA_SEED, int
    )  # default is a concrete int; None is the escape hatch


def test_crag_runtime_constants_match_spec():
    """Verify CRAG runtime constants match specs/005 §6."""
    from app.config import (
        CRAG_TOP_K,
        CRAG_WEB_MAX_RESULTS,
        CRAG_MAX_EVIDENCE_SNIPPETS,
        CRAG_QUERY_MAX_CHARS,
        CRAG_EMBED_TIMEOUT_SECONDS,
        CRAG_WEB_TIMEOUT_SECONDS,
        CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD,
    )

    assert CRAG_TOP_K == 5
    assert CRAG_WEB_MAX_RESULTS == 5
    assert CRAG_MAX_EVIDENCE_SNIPPETS == 5
    assert CRAG_QUERY_MAX_CHARS == 2000
    assert CRAG_EMBED_TIMEOUT_SECONDS == 30
    assert CRAG_WEB_TIMEOUT_SECONDS == 20
    assert CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD == 5


def test_crag_constants_correct_types():
    """Verify types: int counts/timeouts, float threshold, str model/paths."""
    from app import config

    assert isinstance(config.CRAG_TOP_K, int)
    assert isinstance(config.CRAG_WEB_MAX_RESULTS, int)
    assert isinstance(config.CRAG_MAX_EVIDENCE_SNIPPETS, int)
    assert isinstance(config.CRAG_QUERY_MAX_CHARS, int)
    assert isinstance(config.CRAG_EMBED_TIMEOUT_SECONDS, int)
    assert isinstance(config.CRAG_WEB_TIMEOUT_SECONDS, int)
    assert isinstance(config.CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD, int)
    assert isinstance(config.CRAG_CONFIDENCE_THRESHOLD, float)
    assert isinstance(config.OLLAMA_EMBED_MODEL_NAME, str)
    assert isinstance(config.CRAG_KB_INDEX_PATH, str)
    assert isinstance(config.CRAG_KB_METADATA_PATH, str)


def test_embed_model_distinct_from_generative():
    """Constitution §8 model-separation rule (AC-8): embedding model must not
    equal the generative model."""
    from app.config import OLLAMA_EMBED_MODEL_NAME, OLLAMA_MODEL_NAME

    assert OLLAMA_EMBED_MODEL_NAME != OLLAMA_MODEL_NAME
    assert OLLAMA_EMBED_MODEL_NAME == "bge-m3"


def test_self_rag_constants_match_spec():
    """Verify Self-RAG constants match specs/006 §6."""
    from app.config import (
        SELF_RAG_MAX_ATTEMPTS,
        SELF_RAG_TIMEOUT_SECONDS,
        SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD,
        SELF_RAG_PROMPT_MAX_CHARS,
    )

    assert (
        SELF_RAG_MAX_ATTEMPTS == 1
    )  # feature 025 latency lever B (§3): default tuned 3 → 1
    assert SELF_RAG_TIMEOUT_SECONDS == 120
    assert SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD == 5
    assert SELF_RAG_PROMPT_MAX_CHARS == 6000


def test_self_rag_constants_correct_types():
    """int for the numeric constants; frozenset of str for the high-risk set."""
    from app import config

    assert isinstance(config.SELF_RAG_MAX_ATTEMPTS, int)
    assert isinstance(config.SELF_RAG_TIMEOUT_SECONDS, int)
    assert isinstance(config.SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD, int)
    assert isinstance(config.SELF_RAG_PROMPT_MAX_CHARS, int)
    assert isinstance(config.SELF_RAG_HIGH_RISK_CLAUSE_TYPES, frozenset)
    assert all(isinstance(t, str) for t in config.SELF_RAG_HIGH_RISK_CLAUSE_TYPES)
    assert isinstance(config.SELF_RAG_RECALL_FLOOR_TYPES, frozenset)
    assert all(isinstance(t, str) for t in config.SELF_RAG_RECALL_FLOOR_TYPES)


def test_self_rag_high_risk_types_are_valid_clause_types():
    """Every high-risk entry must be a real ClauseType.value (guards typos / enum drift)."""
    from app.config import SELF_RAG_HIGH_RISK_CLAUSE_TYPES
    from app.graph.state import ClauseType

    valid = {ct.value for ct in ClauseType}
    assert SELF_RAG_HIGH_RISK_CLAUSE_TYPES <= valid


def test_self_rag_recall_floor_types_are_valid_clause_types():
    """Every recall-floor entry must be a real ClauseType.value (spec 027, AC-5)."""
    from app.config import SELF_RAG_RECALL_FLOOR_TYPES
    from app.graph.state import ClauseType

    valid = {ct.value for ct in ClauseType}
    assert SELF_RAG_RECALL_FLOOR_TYPES <= valid
    # Harness-tuned default (spec 027 D2/D3): includes confidentiality (rescues a real
    # 026 miss) and EXCLUDES dispute_resolution (dropped after the AC-7 A/B — it caused
    # the governing-law false flag at no recall gain). Guards against silent re-widening.
    assert "confidentiality" in SELF_RAG_RECALL_FLOOR_TYPES
    assert "dispute_resolution" not in SELF_RAG_RECALL_FLOOR_TYPES


def test_llm_provider_and_groq_config_valid():
    """Feature 046 (AC-7): the provider seam config is well-formed and defaults to local ollama."""
    from app.config import (
        LLM_PROVIDER,
        GROQ_MODEL,
        GROQ_REASONING_EFFORT,
        GROQ_MAX_RETRIES,
    )

    assert LLM_PROVIDER in {"ollama", "groq"}
    # Default is the fully-local path (env may override in a deploy, but the shipped default is ollama).
    import os

    if not os.getenv("LLM_PROVIDER"):
        assert LLM_PROVIDER == "ollama"
    assert isinstance(GROQ_MODEL, str) and GROQ_MODEL.strip()
    assert isinstance(GROQ_REASONING_EFFORT, str) and GROQ_REASONING_EFFORT.strip()
    assert isinstance(GROQ_MAX_RETRIES, int)


def test_sublist_split_marker_flag_is_bool():
    """Feature 045 (AC-3): the sub-list-split flag is a bool (reversible master switch)."""
    from app.config import CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS

    assert isinstance(CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS, bool)


def test_ingest_strip_document_chrome_flag_is_bool():
    """Feature 044 (AC-5): the document-chrome strip flag is a bool (reversible master switch)."""
    from app.config import INGEST_STRIP_DOCUMENT_CHROME_ENABLED

    assert isinstance(INGEST_STRIP_DOCUMENT_CHROME_ENABLED, bool)


def test_deterministic_clause_typing_config_is_valid():
    """Feature 042 (AC-4): the tagger flag is a bool and every pattern-map key is a real
    ClauseType.value that is a subset of the recall-floor types (typing a non-floor type
    has no floor effect, D2). Mirrors test_self_rag_recall_floor_types_are_valid_clause_types."""
    from app.config import (
        DETERMINISTIC_CLAUSE_TYPING_ENABLED,
        DETERMINISTIC_CLAUSE_TYPE_PATTERNS,
        SELF_RAG_RECALL_FLOOR_TYPES,
    )
    from app.graph.state import ClauseType

    assert isinstance(DETERMINISTIC_CLAUSE_TYPING_ENABLED, bool)
    # Shipped OFF by default (AC-7 merge gate, 2026-08-19): the mechanism works (027 floor-rescues
    # 0→66, recall +17.4pp) but the false-flag cost (+17.5pp) failed the plan §6 precision gate.
    # Feature is present + reversible, pending phrase-map tightening. Guards against silent re-enable.
    assert DETERMINISTIC_CLAUSE_TYPING_ENABLED is False

    valid = {ct.value for ct in ClauseType}
    keys = {ctype for ctype, _phrases in DETERMINISTIC_CLAUSE_TYPE_PATTERNS}
    # Every key is a real ClauseType.value (guards typos / enum drift)...
    assert keys <= valid
    # ...and only floor types (typing a non-floor type would not change floor behavior, D2).
    assert keys <= SELF_RAG_RECALL_FLOOR_TYPES

    # Each phrase group is a non-empty tuple/list of lowercase phrases (an upper-case phrase
    # could never match the lowercased clause text — guards a silent no-op pattern).
    for _ctype, phrases in DETERMINISTIC_CLAUSE_TYPE_PATTERNS:
        assert isinstance(phrases, (tuple, list)) and len(phrases) > 0
        assert all(isinstance(p, str) and p == p.lower() for p in phrases)


def test_self_rag_lever_c_constants_match_spec():
    """Feature 029 Lever C (§3): merge-judgments toggle + combined-call token cap (AC-18)."""
    from app.config import (
        SELF_RAG_MERGE_JUDGMENTS,
        SELF_RAG_MERGED_NUM_PREDICT,
    )

    assert SELF_RAG_MERGE_JUDGMENTS is False  # 029 merge decision: Lever C ships dormant (default off)
    assert SELF_RAG_MERGED_NUM_PREDICT == 384  # sized for a 3-verdict + reason JSON object


def test_self_rag_lever_c_constants_correct_types():
    """bool toggle, int token cap (AC-18)."""
    from app import config

    assert isinstance(config.SELF_RAG_MERGE_JUDGMENTS, bool)
    assert isinstance(config.SELF_RAG_MERGED_NUM_PREDICT, int)


def test_self_rag_max_retries_renamed():
    """The old placeholder is gone; the renamed constant exists (spec §8b Q2)."""
    from app import config

    assert not hasattr(config, "SELF_RAG_MAX_RETRIES")
    assert hasattr(config, "SELF_RAG_MAX_ATTEMPTS")


def test_self_rag_uses_generative_model():
    """Constitution §8: the generative model is distinct from the embedding model."""
    from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME

    assert OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME
    assert OLLAMA_MODEL_NAME == "qwen3:8b"


def test_risk_score_constants_match_spec():
    """Verify RiskScore numeric constants match specs/007 §6."""
    from app.config import (
        RISK_SCORE_TIMEOUT_SECONDS,
        RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD,
        RISK_SCORE_PROMPT_MAX_CHARS,
        RISK_RATIONALE_MAX_CHARS,
    )

    assert RISK_SCORE_TIMEOUT_SECONDS == 120
    assert RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD == 5
    assert RISK_SCORE_PROMPT_MAX_CHARS == 6000
    assert RISK_RATIONALE_MAX_CHARS == 1000


def test_risk_score_constants_correct_types():
    """int for the numeric constants."""
    from app import config

    assert isinstance(config.RISK_SCORE_TIMEOUT_SECONDS, int)
    assert isinstance(config.RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD, int)
    assert isinstance(config.RISK_SCORE_PROMPT_MAX_CHARS, int)
    assert isinstance(config.RISK_RATIONALE_MAX_CHARS, int)


def test_risk_score_default_level_is_high():
    """Fail-safe default is RiskLevel.HIGH (spec §8a R1)."""
    from app.config import RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE
    from app.graph.state import RiskLevel

    assert RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE is RiskLevel.HIGH
    assert isinstance(RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE, RiskLevel)


def test_risk_score_no_max_attempts_constant():
    """No retry loop for RiskScore (spec §8a R6) — the constant must not exist."""
    from app import config

    assert not hasattr(config, "RISK_SCORE_MAX_ATTEMPTS")


def test_risk_score_uses_generative_model():
    """Constitution §8: the generative model is distinct from the embedding model."""
    from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME

    assert OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME
    assert OLLAMA_MODEL_NAME == "qwen3:8b"


def test_redline_constants_match_spec():
    """Verify Redline numeric constants match specs/008 §6."""
    from app.config import (
        REDLINE_TIMEOUT_SECONDS,
        REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD,
        REDLINE_PROMPT_MAX_CHARS,
        REDLINE_PROMPT_RATIONALE_RESERVE_CHARS,
        REDLINE_REWRITE_MAX_CHARS,
    )

    assert REDLINE_TIMEOUT_SECONDS == 120
    assert REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD == 5
    assert REDLINE_PROMPT_MAX_CHARS == 6000
    assert REDLINE_PROMPT_RATIONALE_RESERVE_CHARS == 1000
    assert REDLINE_REWRITE_MAX_CHARS == 4000


def test_redline_constants_correct_types():
    """int for the numeric constants; frozenset for the threshold."""
    from app import config

    assert isinstance(config.REDLINE_TIMEOUT_SECONDS, int)
    assert isinstance(config.REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD, int)
    assert isinstance(config.REDLINE_PROMPT_MAX_CHARS, int)
    assert isinstance(config.REDLINE_PROMPT_RATIONALE_RESERVE_CHARS, int)
    assert isinstance(config.REDLINE_REWRITE_MAX_CHARS, int)
    assert isinstance(config.REDLINE_RISK_THRESHOLD, frozenset)


def test_redline_threshold_is_all_levels():
    """Resolved Option A (spec §8a R1): all three levels are redline-eligible."""
    from app.config import REDLINE_RISK_THRESHOLD
    from app.graph.state import RiskLevel

    assert REDLINE_RISK_THRESHOLD == frozenset(
        {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH}
    )
    assert all(isinstance(x, RiskLevel) for x in REDLINE_RISK_THRESHOLD)


def test_redline_rationale_reserve_within_prompt_budget():
    """The reserve is a partition of the prompt budget, never larger than it."""
    from app.config import (
        REDLINE_PROMPT_RATIONALE_RESERVE_CHARS,
        REDLINE_PROMPT_MAX_CHARS,
    )

    assert REDLINE_PROMPT_RATIONALE_RESERVE_CHARS < REDLINE_PROMPT_MAX_CHARS


def test_redline_no_max_attempts_constant():
    """No retry loop for Redline (spec §6) — the constant must not exist."""
    from app import config

    assert not hasattr(config, "REDLINE_MAX_ATTEMPTS")


def test_redline_uses_generative_model():
    """Constitution §8: the generative model is distinct from the embedding model."""
    from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME

    assert OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME
    assert OLLAMA_MODEL_NAME == "qwen3:8b"


def test_report_constants_match_spec():
    """Verify Report constants match specs/009 §6."""
    from app.config import (
        REPORT_OUTPUT_DIR,
        REPORT_MD_FILENAME_TEMPLATE,
        REPORT_JSON_FILENAME_TEMPLATE,
        REPORT_EVIDENCE_TEXT_MAX_CHARS,
    )

    assert REPORT_OUTPUT_DIR == "data/reports"
    assert REPORT_MD_FILENAME_TEMPLATE == "{document_id}.md"
    assert REPORT_JSON_FILENAME_TEMPLATE == "{document_id}.json"
    assert REPORT_EVIDENCE_TEXT_MAX_CHARS == 2000


def test_report_constants_correct_types():
    """str for the dir + templates; int for the char cap."""
    from app import config

    assert isinstance(config.REPORT_OUTPUT_DIR, str)
    assert isinstance(config.REPORT_MD_FILENAME_TEMPLATE, str)
    assert isinstance(config.REPORT_JSON_FILENAME_TEMPLATE, str)
    assert isinstance(config.REPORT_EVIDENCE_TEXT_MAX_CHARS, int)


def test_report_filename_templates_have_document_id():
    """Both templates are keyed on document_id and differ only by extension (D6)."""
    from app.config import (
        REPORT_MD_FILENAME_TEMPLATE,
        REPORT_JSON_FILENAME_TEMPLATE,
    )

    assert "{document_id}" in REPORT_MD_FILENAME_TEMPLATE
    assert "{document_id}" in REPORT_JSON_FILENAME_TEMPLATE
    assert REPORT_MD_FILENAME_TEMPLATE.endswith(".md")
    assert REPORT_JSON_FILENAME_TEMPLATE.endswith(".json")
    assert (
        REPORT_MD_FILENAME_TEMPLATE.rsplit(".", 1)[0]
        == REPORT_JSON_FILENAME_TEMPLATE.rsplit(".", 1)[0]
    )


def test_report_no_llm_constant():
    """Node 7 makes no LLM call (D3) — no timeout/model/circuit-breaker constant."""
    from app import config

    assert not hasattr(config, "REPORT_TIMEOUT_SECONDS")
    assert not hasattr(config, "REPORT_LLM_CIRCUIT_BREAKER_THRESHOLD")
    assert not hasattr(config, "REPORT_MODEL_NAME")


def test_mcp_delivery_constants_match_spec():
    """Verify MCP delivery constants match specs/010 §6."""
    from app import config

    assert config.MCP_DELIVERY_ENABLED is True
    assert config.MCP_DRIVE_ENABLED is True
    assert config.MCP_GMAIL_ENABLED is True
    assert isinstance(config.MCP_DELIVERY_RECIPIENT, str)
    assert config.MCP_DRIVE_FOLDER_ID is None
    assert config.MCP_DRIVE_UPLOAD_FORMATS == ("pdf", "json")  # feature 030: PDF supersedes md for humans
    assert config.MCP_GMAIL_ATTACH_REPORT is True
    assert config.MCP_DELIVERY_TIMEOUT_SECONDS == 60
    assert config.MCP_DELIVERY_MAX_RETRIES == 2
    assert (
        config.GOOGLE_OAUTH_CREDENTIALS_PATH == "data/secrets/google_credentials.json"
    )
    assert config.GOOGLE_OAUTH_TOKEN_PATH == "data/secrets/google_token.json"


def test_mcp_delivery_no_llm_constant():
    """Delivery makes no LLM call — no model/timeout-LLM/circuit-breaker constant."""
    from app import config

    assert not hasattr(config, "MCP_DELIVERY_MODEL_NAME")
    assert not hasattr(config, "MCP_DELIVERY_LLM_CIRCUIT_BREAKER_THRESHOLD")


def test_mcp_upload_formats_are_report_extensions():
    """Uploaded formats must be a subset of the renderable delivery formats. Feature 030
    adds `pdf` (a delivery-time artifact) alongside the Node-7 outputs {md, json}; the
    invariant still guards against typos / arbitrary extensions."""
    from app import config

    assert set(config.MCP_DRIVE_UPLOAD_FORMATS) <= {"md", "json", "pdf"}


def test_report_delivery_030_constants_match_spec():
    """Feature 030 Phase 1 constants (§3): PDF renderer + branded email (AC-17)."""
    from app import config

    assert config.MCP_GMAIL_ATTACH_FORMAT == "pdf"
    assert config.MCP_REPORT_PDF_ENABLED is True
    assert config.REPORT_PDF_CLAUSE_MAX_CHARS == 2000
    assert config.REPORT_PDF_RATIONALE_MAX_CHARS == 1500
    assert config.REPORT_PDF_REWRITE_MAX_CHARS == 4000
    assert config.REPORT_BRAND_NAME == "ContractSentinel"
    assert config.REPORT_BRAND_ACCENT_HEX == "#1e293b"
    assert isinstance(config.REPORT_BRAND_FOOTER, str) and config.REPORT_BRAND_FOOTER


def test_report_delivery_030_constants_correct_types():
    """str/bool/int types for the feature-030 constants (AC-17)."""
    from app import config

    assert isinstance(config.MCP_GMAIL_ATTACH_FORMAT, str)
    assert isinstance(config.MCP_REPORT_PDF_ENABLED, bool)
    assert isinstance(config.REPORT_PDF_CLAUSE_MAX_CHARS, int)
    assert isinstance(config.REPORT_PDF_RATIONALE_MAX_CHARS, int)
    assert isinstance(config.REPORT_PDF_REWRITE_MAX_CHARS, int)
    assert isinstance(config.REPORT_BRAND_NAME, str)
    assert isinstance(config.REPORT_BRAND_ACCENT_HEX, str)


def test_runner_api_constants_match_spec():
    """Verify Runner/API constants match specs/011 §6.1."""
    from app import config

    assert config.UPLOAD_DIR == "data/uploads"
    assert config.MAX_UPLOAD_SIZE_BYTES == 25 * 1024 * 1024
    assert config.ALLOWED_UPLOAD_EXTENSIONS == frozenset({".pdf", ".docx"})
    assert config.RUNNER_WORKER_CONCURRENCY == 1
    assert config.JOB_REGISTRY_MAX == 500
    assert tuple(config.CORS_ALLOWED_ORIGINS) == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    assert config.API_BIND_HOST == "127.0.0.1"
    assert config.API_BIND_PORT == 8000


def test_upload_extensions_match_ingest():
    """The API's accepted extensions must mirror IngestAgent's, so the boundary and the
    node agree on what is a valid contract (drift lock — spec AC-15)."""
    from app import config
    from app.graph.nodes.ingest_agent import ALLOWED_EXTENSIONS

    assert set(config.ALLOWED_UPLOAD_EXTENSIONS) == set(ALLOWED_EXTENSIONS)


def test_bind_host_is_localhost():
    """D1: never an accidental public bind."""
    from app import config

    assert config.API_BIND_HOST == "127.0.0.1"


def test_runner_no_llm_constant():
    """The runner makes no LLM call — no model/timeout-LLM/circuit-breaker constant (D6)."""
    from app import config

    assert not hasattr(config, "RUNNER_MODEL_NAME")
    assert not hasattr(config, "RUNNER_TIMEOUT_SECONDS")
    assert not hasattr(config, "RUNNER_LLM_CIRCUIT_BREAKER_THRESHOLD")


def test_persistence_constants_match_spec():
    """Verify durable-persistence constants match specs/012 §6.1."""
    from app import config

    assert config.JOB_STORE_DB_PATH == "data/job_store.db"
    assert config.CHECKPOINTER_DB_PATH == "data/checkpoints.db"
    assert config.CHECKPOINTER_ENABLED is True
    assert config.JOB_STORE_RETENTION_MAX == 500
    assert config.STARTUP_RECOVERY_ENABLED is True


def test_persistence_constants_correct_types():
    """str for paths, bool for flags, int for the cap."""
    from app import config

    assert isinstance(config.JOB_STORE_DB_PATH, str)
    assert isinstance(config.CHECKPOINTER_DB_PATH, str)
    assert isinstance(config.CHECKPOINTER_ENABLED, bool)
    assert isinstance(config.JOB_STORE_RETENTION_MAX, int)
    assert isinstance(config.STARTUP_RECOVERY_ENABLED, bool)


def test_job_registry_max_alias():
    """JOB_REGISTRY_MAX is an alias for JOB_STORE_RETENTION_MAX (spec D5)."""
    from app import config

    assert config.JOB_REGISTRY_MAX == config.JOB_STORE_RETENTION_MAX


def test_per_user_drive_031_constants_match_spec():
    """Feature 031 per-user Drive constants (§3, AC-16)."""
    from app import config as c
    assert c.PER_USER_DRIVE_ENABLED is True
    assert c.GOOGLE_OAUTH_REDIRECT_URI == "http://localhost:8000/api/integrations/google/callback"
    assert c.GOOGLE_DRIVE_OAUTH_SCOPES == ("https://www.googleapis.com/auth/drive.file",)
    assert c.GOOGLE_OAUTH_WEB_CREDENTIALS_PATH == "data/secrets/google_web_credentials.json"
    assert c.FRONTEND_INTEGRATIONS_URL == "http://localhost:3000/integrations"


def test_per_user_drive_031_constants_types():
    from app import config as c
    assert isinstance(c.PER_USER_DRIVE_ENABLED, bool)
    assert isinstance(c.GOOGLE_OAUTH_REDIRECT_URI, str)
    assert isinstance(c.GOOGLE_DRIVE_OAUTH_SCOPES, tuple)
    assert isinstance(c.GOOGLE_OAUTH_WEB_CREDENTIALS_PATH, str)
    assert isinstance(c.FRONTEND_INTEGRATIONS_URL, str)


# ── Feature 048: cross-origin deploy config (env-overridable CORS + cookie SameSite) ──
# Tests exercise the named helpers directly (no importlib.reload) — see plan §5.


def test_cors_allowed_origins_default_unchanged():
    """AC-1: with no env override, defaults are byte-identical to pre-048 localhost tuple."""
    from app import config as c
    assert c.CORS_ALLOWED_ORIGINS == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )


def test_env_origin_tuple_parses_csv(monkeypatch):
    """AC-2: comma-separated env → trimmed, order-preserved tuple."""
    from app import config as c
    monkeypatch.setenv("CS_TEST_ORIGINS", "https://cs.vercel.app, https://foo.dev")
    assert c._env_origin_tuple("CS_TEST_ORIGINS", ("x",)) == (
        "https://cs.vercel.app",
        "https://foo.dev",
    )


def test_env_origin_tuple_blank_falls_back_to_default(monkeypatch):
    """Edge (reviewer ambiguity): unset / empty / comma-only env → the default tuple, never empty."""
    from app import config as c
    default = ("http://localhost:5173",)
    monkeypatch.delenv("CS_TEST_ORIGINS", raising=False)
    assert c._env_origin_tuple("CS_TEST_ORIGINS", default) == default
    monkeypatch.setenv("CS_TEST_ORIGINS", "")
    assert c._env_origin_tuple("CS_TEST_ORIGINS", default) == default
    monkeypatch.setenv("CS_TEST_ORIGINS", " , ,")
    assert c._env_origin_tuple("CS_TEST_ORIGINS", default) == default


def test_auth_cookie_samesite_default_is_lax():
    """AC-3: default SameSite unchanged from today."""
    from app import config as c
    assert c.AUTH_COOKIE_SAMESITE == "lax"


def test_env_samesite_normalizes_none(monkeypatch):
    """AC-4: any-case 'None' → normalized 'none'."""
    from app import config as c
    monkeypatch.setenv("CS_TEST_SS", "None")
    assert c._env_samesite("CS_TEST_SS", "lax") == "none"


def test_env_samesite_invalid_falls_back_to_default(monkeypatch):
    """AC-5: unrecognized / whitespace-only value → safe default (lax)."""
    from app import config as c
    monkeypatch.setenv("CS_TEST_SS", "bogus")
    assert c._env_samesite("CS_TEST_SS", "lax") == "lax"
    monkeypatch.setenv("CS_TEST_SS", "   ")
    assert c._env_samesite("CS_TEST_SS", "lax") == "lax"


def test_validate_samesite_secure_guard():
    """AC-7: SameSite=none without Secure raises, naming both vars; valid combos do not raise."""
    import pytest
    from app import config as c
    with pytest.raises(ValueError, match="AUTH_COOKIE_SAMESITE.*AUTH_COOKIE_SECURE"):
        c._validate_samesite_secure("none", secure=False)
    assert c._validate_samesite_secure("none", secure=True) is None
    assert c._validate_samesite_secure("lax", secure=False) is None


# ── Feature 049: prod URL config (env-overridable OAuth redirect + frontend URL) ──
# Helpers tested directly (no importlib.reload) — same precedent as 048 above.


def test_env_str_reads_override(monkeypatch):
    """AC-3/AC-4: a set, non-blank env value is returned (trimmed)."""
    from app import config as c
    monkeypatch.setenv("CS_TEST_REDIRECT", "https://api.example.com/api/integrations/google/callback")
    assert (
        c._env_str("CS_TEST_REDIRECT", "x")
        == "https://api.example.com/api/integrations/google/callback"
    )
    monkeypatch.setenv("CS_TEST_FRONT", "  https://app.example.com/integrations  ")
    assert c._env_str("CS_TEST_FRONT", "x") == "https://app.example.com/integrations"


def test_env_str_blank_or_unset_falls_back(monkeypatch):
    """Edge: unset / empty / whitespace-only env ⇒ the default (never an empty URL)."""
    from app import config as c
    monkeypatch.delenv("CS_TEST_UNSET", raising=False)
    assert c._env_str("CS_TEST_UNSET", "def") == "def"
    monkeypatch.setenv("CS_TEST_UNSET", "")
    assert c._env_str("CS_TEST_UNSET", "def") == "def"
    monkeypatch.setenv("CS_TEST_UNSET", "   ")
    assert c._env_str("CS_TEST_UNSET", "def") == "def"


def test_prod_url_defaults_byte_identical():
    """AC-1/AC-2: unset env ⇒ the pre-049 localhost defaults (031 tests also pin these)."""
    from app import config as c
    assert c.GOOGLE_OAUTH_REDIRECT_URI == "http://localhost:8000/api/integrations/google/callback"
    assert c.FRONTEND_INTEGRATIONS_URL == "http://localhost:3000/integrations"
