"""
Severity judgment for the RiskScore node (Node 5).

score_risk makes a single generative LLM call per validated finding and returns
(RiskLevel, rationale) or None on any failure. Never raises — the caller
(risk_score_agent) interprets None as an unrecoverable failure and applies the
fail-safe default, counting it toward the circuit breaker.
"""

import concurrent.futures
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
import ollama

from app.graph.state import RiskLevel
from app.graph.nodes.validators import format_evidence

logger = logging.getLogger("contractsentinel.risk_score.scorer")

_SCORING_WITH_EVIDENCE_PROMPT = """\
You are a contract-risk analysis assistant. Your task is to assess the severity \
of the following contract clause as a legal risk finding.

This clause is categorized as: {clause_type}

Scoring rubric:
- "low": a minor or standard deviation from typical contract terms; low financial \
or legal exposure.
- "medium": a materially one-sided or non-standard term that could lead to \
meaningful financial or legal disadvantage.
- "high": a severe, uncapped, or unilateral risk — e.g. unlimited liability, \
broad indemnification, unilateral termination, forced IP assignment, or \
similarly extreme terms.

Respond with ONLY a JSON object — no markdown, no explanation:
{{"risk_level": "low"|"medium"|"high", "rationale": "<one or two sentences>"}}

Contract clause:
{clause_text}

Supporting evidence:
{evidence_text}
"""

_SCORING_TEXT_ONLY_PROMPT = """\
You are a contract-risk analysis assistant. Your task is to assess the severity \
of the following contract clause as a legal risk finding. No retrieved evidence \
is available — judge SOLELY on the clause text and its category.

This clause is categorized as: {clause_type}

Scoring rubric:
- "low": a minor or standard deviation from typical contract terms; low financial \
or legal exposure.
- "medium": a materially one-sided or non-standard term that could lead to \
meaningful financial or legal disadvantage.
- "high": a severe, uncapped, or unilateral risk — e.g. unlimited liability, \
broad indemnification, unilateral termination, forced IP assignment, or \
similarly extreme terms.

Respond with ONLY a JSON object — no markdown, no explanation:
{{"risk_level": "low"|"medium"|"high", "rationale": "<one or two sentences>"}}

Contract clause:
{clause_text}
"""


def score_risk(
    clause_text: str,
    evidence_snippets: Optional[List[Dict[str, Any]]],
    clause_type: Optional[str],
    timeout_seconds: int,
    model_name: str,
    prompt_max_chars: int,
) -> Optional[Tuple[RiskLevel, str]]:
    """Single generative call assigning Low/Medium/High severity to a validated
    finding, plus a short rationale. evidence_snippets (001 shape) is scoring
    context when present; may be []/None (Self-RAG rescue path) → judge on clause
    text + clause_type alone. clause_type is a normalized string label (or None).
    Returns (RiskLevel, rationale) or None on any failure. Never raises."""
    clause_trunc = clause_text[:prompt_max_chars]
    if len(clause_text) > len(clause_trunc):
        logger.debug(
            "RiskScore: clause text truncated from %d to %d chars (budget=%d) before scoring",
            len(clause_text),
            len(clause_trunc),
            prompt_max_chars,
        )
    remaining = max(0, prompt_max_chars - len(clause_trunc))
    evidence_str = format_evidence(evidence_snippets, remaining)
    if evidence_snippets and len(evidence_str) == remaining:
        # format_evidence clipped the concatenated evidence to the remaining budget
        logger.debug(
            "RiskScore: evidence snippets truncated to remaining prompt budget of %d chars",
            remaining,
        )
    ct_label = clause_type or "unspecified"

    if evidence_str:
        prompt = _SCORING_WITH_EVIDENCE_PROMPT.format(
            clause_type=ct_label,
            clause_text=clause_trunc,
            evidence_text=evidence_str,
        )
    else:
        prompt = _SCORING_TEXT_ONLY_PROMPT.format(
            clause_type=ct_label,
            clause_text=clause_trunc,
        )

    return _run_scoring(prompt, timeout_seconds, model_name)


def _run_scoring(
    prompt: str, timeout_seconds: int, model_name: str
) -> Optional[Tuple[RiskLevel, str]]:
    """Submit a scoring prompt to Ollama and parse the (RiskLevel, rationale) result.

    Uses ollama.Client(timeout=...) as the primary abort bound (kills the
    underlying httpx call so a hung socket cannot outlive the timeout),
    with ThreadPoolExecutor.future.result(timeout=...) as a backstop.
    Mirrors reflectors._run_judgment. Never raises — all failures return None.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_ollama, prompt, timeout_seconds, model_name)
        try:
            return future.result(timeout=timeout_seconds)
        except (concurrent.futures.TimeoutError, httpx.TimeoutException):
            logger.warning("RiskScore LLM scoring timed out after %ds", timeout_seconds)
            return None
        except Exception:
            logger.warning("RiskScore LLM scoring failed", exc_info=True)
            return None


def _call_ollama(
    prompt: str, timeout_seconds: int, model_name: str
) -> Optional[Tuple[RiskLevel, str]]:
    """Perform the Ollama chat call and parse the score. Raises on any error."""
    client = ollama.Client(timeout=timeout_seconds)
    response = client.chat(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        think=False,  # qwen3 thinking mode + format="json" wastes the token budget
        # on hidden reasoning and blows the timeout; the JSON answer never needs it.
        options={"num_predict": 384},
    )
    raw = response["message"]["content"]
    return _parse_score(raw)


def _parse_score(raw: str) -> Optional[Tuple[RiskLevel, str]]:
    """Parse the JSON score from the LLM response.

    Returns (RiskLevel, rationale) on success. Any parse error, missing/invalid
    risk_level, or non-string risk_level → None (fail-safe trigger).
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "RiskScore: LLM returned non-JSON (first 200 chars): %r", raw[:200]
        )
        return None

    level_raw = data.get("risk_level")
    if not isinstance(level_raw, str):
        logger.warning(
            "RiskScore: risk_level is not a string (got %r of type %s)",
            level_raw,
            type(level_raw).__name__,
        )
        return None

    try:
        level = RiskLevel(level_raw.strip().lower())
    except ValueError:
        logger.warning(
            "RiskScore: invalid risk_level value %r (not one of low/medium/high)",
            level_raw,
        )
        return None

    rationale = str(data.get("rationale") or "").strip()
    if not rationale:
        # A valid level with no explanation does not satisfy the scoring contract
        # (spec AC-1 requires a non-empty rationale); treat as unparseable so the
        # node applies the fail-safe default rather than persisting an empty one.
        logger.warning(
            "RiskScore: LLM returned risk_level %r but an empty rationale; "
            "treating as unparseable (fail-safe)",
            level_raw,
        )
        return None
    return (level, rationale)
