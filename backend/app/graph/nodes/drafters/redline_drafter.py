"""
Rewrite generation for the Redline node (Node 6).

draft_rewrite makes a single generative LLM call per redline-eligible clause and
returns the safer rewrite string, or None on any failure. Never raises — the
caller (redline_agent) interprets None as an unrecoverable failure, emits
suggested_rewrite: None, and counts it toward the circuit breaker.
"""

import concurrent.futures
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
import ollama

from app.graph.nodes.validators import format_evidence

import app.config as _config

# Read by bare name below (never via _config.NAME) so tests monkeypatch the node-module attr
# — feature 028 determinism sampling options; mirrors the 027 alias pattern.
OLLAMA_TEMPERATURE = _config.OLLAMA_TEMPERATURE
OLLAMA_SEED = _config.OLLAMA_SEED

logger = logging.getLogger("contractsentinel.redline.drafter")

_REWRITE_WITH_EVIDENCE_PROMPT = """\
You are a contract-risk remediation assistant. Your task is to rewrite the \
following contract clause to neutralize the identified risk while preserving \
the clause's legitimate commercial intent.

This clause is categorized as: {clause_type}

This clause was flagged as risky because: {rationale}

Supporting evidence from legal knowledge base:
{evidence_text}

Contract clause to rewrite:
{clause_text}

Respond with ONLY a JSON object — no markdown, no explanation:
{{"suggested_rewrite": "<rewritten clause text>"}}
"""

_REWRITE_TEXT_ONLY_PROMPT = """\
You are a contract-risk remediation assistant. Your task is to rewrite the \
following contract clause to neutralize the identified risk while preserving \
the clause's legitimate commercial intent. No retrieved evidence is available — \
rewrite based on the clause text and the risk rationale alone.

This clause is categorized as: {clause_type}

This clause was flagged as risky because: {rationale}

Contract clause to rewrite:
{clause_text}

Respond with ONLY a JSON object — no markdown, no explanation:
{{"suggested_rewrite": "<rewritten clause text>"}}
"""


def draft_rewrite(
    clause_text: str,
    risk_rationale: Optional[str],
    evidence_snippets: Optional[List[Dict[str, Any]]],
    clause_type: Optional[str],
    timeout_seconds: int,
    model_name: str,
    prompt_max_chars: int,
    rationale_reserve: int,
) -> Optional[str]:
    """Single generative call producing safer replacement language for a
    redline-eligible clause. risk_rationale (the Node-5 explanation of WHY the clause
    is risky) is the remediation target fed to the prompt. evidence_snippets (001
    shape) is drafting context when present; may be []/None (Self-RAG rescue path) →
    draft on clause text + risk_rationale + clause_type alone. clause_type is a
    normalized string label (or None). Returns the rewrite string (untruncated — the
    node applies REDLINE_REWRITE_MAX_CHARS) or None on any failure / empty output.
    Never raises."""
    rationale_full = (risk_rationale or "").strip()

    # Reserve a rationale floor BEFORE truncating the clause so a clause longer
    # than prompt_max_chars cannot starve the rationale (the remediation target).
    reserve = min(len(rationale_full), rationale_reserve)
    clause_budget = max(0, prompt_max_chars - reserve)
    clause_trunc = clause_text[:clause_budget]
    if len(clause_text) > len(clause_trunc):
        logger.debug(
            "Redline: clause text truncated from %d to %d chars (budget=%d) before drafting",
            len(clause_text),
            len(clause_trunc),
            clause_budget,
        )

    remaining = max(0, prompt_max_chars - len(clause_trunc))
    rationale_trunc = rationale_full[:remaining]
    if rationale_full and len(rationale_full) > len(rationale_trunc):
        logger.debug(
            "Redline: rationale truncated from %d to %d chars before drafting",
            len(rationale_full),
            len(rationale_trunc),
        )

    remaining = max(0, remaining - len(rationale_trunc))
    evidence_str = format_evidence(evidence_snippets, remaining)
    if evidence_snippets and evidence_str and len(evidence_str) == remaining:
        logger.debug(
            "Redline: evidence snippets truncated to remaining prompt budget of %d chars",
            remaining,
        )

    ct_label = clause_type or "unspecified"

    if evidence_str:
        prompt = _REWRITE_WITH_EVIDENCE_PROMPT.format(
            clause_type=ct_label,
            rationale=rationale_trunc or "No rationale provided.",
            evidence_text=evidence_str,
            clause_text=clause_trunc,
        )
    else:
        prompt = _REWRITE_TEXT_ONLY_PROMPT.format(
            clause_type=ct_label,
            rationale=rationale_trunc or "No rationale provided.",
            clause_text=clause_trunc,
        )

    return _run_drafting(prompt, timeout_seconds, model_name)


def _run_drafting(prompt: str, timeout_seconds: int, model_name: str) -> Optional[str]:
    """Submit a drafting prompt to Ollama and parse the suggested_rewrite result.

    Uses ollama.Client(timeout=...) as the primary abort bound (kills the
    underlying httpx call so a hung socket cannot outlive the timeout),
    with ThreadPoolExecutor.future.result(timeout=...) as a backstop.
    Mirrors risk_scorer._run_scoring. Never raises — all failures return None.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_ollama, prompt, timeout_seconds, model_name)
        try:
            return future.result(timeout=timeout_seconds)
        except (concurrent.futures.TimeoutError, httpx.TimeoutException):
            logger.warning("Redline LLM drafting timed out after %ds", timeout_seconds)
            return None
        except Exception:
            logger.warning("Redline LLM drafting failed", exc_info=True)
            return None


def _call_ollama(prompt: str, timeout_seconds: int, model_name: str) -> Optional[str]:
    """Perform the Ollama chat call and parse the rewrite. Raises on any error."""
    client = ollama.Client(timeout=timeout_seconds)
    response = client.chat(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        think=False,  # qwen3 thinking mode + format="json" wastes the token budget
        # on hidden reasoning and blows the timeout; the JSON answer never needs it.
        options={
            "num_predict": 1536,
            "temperature": OLLAMA_TEMPERATURE,
            **({"seed": OLLAMA_SEED} if OLLAMA_SEED is not None else {}),
        },
    )
    raw = response["message"]["content"]
    return _parse_rewrite(raw)


def _parse_rewrite(raw: str) -> Optional[str]:
    """Parse the JSON rewrite from the LLM response.

    Returns the stripped rewrite string on success (untruncated — the node
    applies REDLINE_REWRITE_MAX_CHARS). Empty/whitespace-only output, non-string
    values, missing key, or non-JSON body → None (drafting failure).
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "Redline: LLM returned non-JSON (first 200 chars): %r", raw[:200]
        )
        return None

    rewrite_raw = data.get("suggested_rewrite")
    if not isinstance(rewrite_raw, str):
        logger.warning(
            "Redline: suggested_rewrite is not a string (got %r of type %s)",
            rewrite_raw,
            type(rewrite_raw).__name__,
        )
        return None

    rewrite = rewrite_raw.strip()
    if not rewrite:
        logger.warning("Redline: LLM returned empty/whitespace suggested_rewrite")
        return None

    return rewrite
