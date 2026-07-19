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

    assert SELF_RAG_MAX_ATTEMPTS == 1  # feature 025 latency lever B (§3): default tuned 3 → 1
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
    assert config.MCP_DRIVE_UPLOAD_FORMATS == ("md", "json")
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
    """Uploaded formats must be a subset of Node-7's output extensions {md, json}."""
    from app import config

    assert set(config.MCP_DRIVE_UPLOAD_FORMATS) <= {"md", "json"}


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
