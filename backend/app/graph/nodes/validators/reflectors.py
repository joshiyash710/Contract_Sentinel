"""
Reflective judgment functions for the Self-RAG validation node (Node 4).

Each public function returns Optional[bool] and NEVER raises — the caller
interprets None as an unrecoverable LLM failure and applies the fail-open
default (spec §4.4 / §8a R3).
"""

import concurrent.futures
import json
import logging
from typing import List, Dict, Any, Optional

import httpx
import ollama

from app.graph.nodes.validators import format_evidence

logger = logging.getLogger("contractsentinel.self_rag_validation.reflectors")

_RELEVANCE_PROMPT = """\
You are a contract-risk analysis assistant. Your task is to decide whether the \
following contract clause is a SUBSTANTIVE provision — one that could plausibly \
carry a contractual concern worth evaluating (e.g. obligations, rights, \
liabilities, deadlines, restrictions, IP assignment, termination rights).

Respond with ONLY a JSON object — no markdown, no explanation:
{{"verdict": true, "reason": "<one short sentence>"}}

Set "verdict" to true if the clause IS a substantive, analyzable provision.
Set "verdict" to false if the clause is boilerplate / structural filler \
(e.g. a page header, a definitions list with no substantive content, a \
signature block, or blank / numbering-only text).

Clause text:
{clause_text}
"""

_ISREL_PROMPT = """\
You are a contract-risk analysis assistant. Your task is to decide whether the \
retrieved evidence is ON-TOPIC and RELEVANT to the following contract clause.

Respond with ONLY a JSON object — no markdown, no explanation:
{{"verdict": true, "reason": "<one short sentence>"}}

Set "verdict" to true if the evidence directly addresses the legal issue \
raised by this clause (e.g. relevant case law, regulatory text, or market \
norms that bear on the clause's terms).
Set "verdict" to false if the evidence is off-topic, too generic, or \
clearly about a different legal domain than the clause.

Contract clause:
{clause_text}

Retrieved evidence:
{evidence_text}
"""

_ISSUP_WITH_EVIDENCE_PROMPT = """\
You are a contract-risk analysis assistant. Your task is to decide whether \
the evidence SUPPORTS flagging this contract clause as a concern worth \
surfacing to a reviewer (i.e. the clause poses a material contractual risk).

Respond with ONLY a JSON object — no markdown, no explanation:
{{"verdict": true, "reason": "<one short sentence>"}}

Set "verdict" to true if the clause, in light of the evidence, represents \
a meaningful risk (one-sided obligation, missing protection, unusual liability \
shift, IP assignment issue, punitive termination right, etc.).
Set "verdict" to false if the clause appears standard/balanced or the \
evidence does not support flagging it.

Contract clause:
{clause_text}

Supporting evidence:
{evidence_text}
"""

_ISSUP_TEXT_ONLY_PROMPT = """\
You are a contract-risk analysis assistant. No retrieved evidence is available \
for this clause — judge SOLELY on the clause text itself.

Your task is to decide whether this contract clause on its own represents \
a material contractual risk worth surfacing to a reviewer.

Respond with ONLY a JSON object — no markdown, no explanation:
{{"verdict": true, "reason": "<one short sentence>"}}

Set "verdict" to true if the clause is self-evidently risky on its face \
(e.g. an uncapped liability cap, a unilateral termination right, a broad IP \
assignment, a forced-forum clause in an unfavourable jurisdiction).
Set "verdict" to false if the clause appears standard or low-risk.

Contract clause:
{clause_text}
"""


def check_relevance(
    clause_text: str,
    timeout_seconds: int,
    model_name: str,
    prompt_max_chars: int,
) -> Optional[bool]:
    """Relevance: is this clause a substantive, analyzable provision worth
    evaluating at all? A property of the CLAUSE — does NOT read evidence.
    Returns True/False, or None on any LLM failure. Never raises.
    """
    clause_trunc = clause_text[:prompt_max_chars]
    prompt = _RELEVANCE_PROMPT.format(clause_text=clause_trunc)
    return _run_judgment(prompt, timeout_seconds, model_name)


def check_isrel(
    clause_text: str,
    evidence_snippets: List[Dict[str, Any]],
    timeout_seconds: int,
    model_name: str,
    prompt_max_chars: int,
) -> Optional[bool]:
    """ISREL: is the retrieved evidence relevant to this clause? A property of
    the EVIDENCE. Only called when evidence is present.
    Returns True/False, or None on any LLM failure. Never raises.
    """
    clause_trunc = clause_text[:prompt_max_chars]
    remaining = max(0, prompt_max_chars - len(clause_trunc))
    evidence_str = format_evidence(evidence_snippets, remaining)
    prompt = _ISREL_PROMPT.format(clause_text=clause_trunc, evidence_text=evidence_str)
    return _run_judgment(prompt, timeout_seconds, model_name)


def check_issup(
    clause_text: str,
    evidence_snippets: Optional[List[Dict[str, Any]]],
    timeout_seconds: int,
    model_name: str,
    prompt_max_chars: int,
) -> Optional[bool]:
    """ISSUP ('worth flagging'): does the evidence support surfacing this clause
    as a concern? If evidence_snippets is empty/None (the high-risk rescue path,
    spec §7.5), the prompt instructs the model to judge on the CLAUSE TEXT ALONE.
    Returns True/False, or None on any LLM failure. Never raises.
    """
    clause_trunc = clause_text[:prompt_max_chars]
    if not evidence_snippets:
        prompt = _ISSUP_TEXT_ONLY_PROMPT.format(clause_text=clause_trunc)
    else:
        remaining = max(0, prompt_max_chars - len(clause_trunc))
        evidence_str = format_evidence(evidence_snippets, remaining)
        prompt = _ISSUP_WITH_EVIDENCE_PROMPT.format(
            clause_text=clause_trunc, evidence_text=evidence_str
        )
    return _run_judgment(prompt, timeout_seconds, model_name)


def _run_judgment(prompt: str, timeout_seconds: int, model_name: str) -> Optional[bool]:
    """Submit a judgment prompt to Ollama and parse the bool verdict.

    Uses ollama.Client(timeout=...) as the primary abort bound (kills the
    underlying httpx call so a hung socket cannot outlive the timeout),
    with ThreadPoolExecutor.future.result(timeout=...) as a backstop.
    Mirrors llm_refiner.py:67-80, 102-108. Never raises — all failures
    return None.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_ollama, prompt, timeout_seconds, model_name)
        try:
            return future.result(timeout=timeout_seconds)
        except (concurrent.futures.TimeoutError, httpx.TimeoutException):
            logger.warning("Self-RAG LLM judgment timed out after %ds", timeout_seconds)
            return None
        except Exception:
            logger.warning("Self-RAG LLM judgment failed", exc_info=True)
            return None


def _call_ollama(prompt: str, timeout_seconds: int, model_name: str) -> Optional[bool]:
    """Perform the Ollama chat call and parse the verdict. Raises on any error."""
    client = ollama.Client(timeout=timeout_seconds)
    response = client.chat(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        think=False,  # qwen3 thinking mode + format="json" wastes the token budget
        # on hidden reasoning and blows the timeout; the JSON answer never needs it.
        options={"num_predict": 256},
    )
    raw = response["message"]["content"]
    return _parse_verdict(raw)


def _parse_verdict(raw: str) -> Optional[bool]:
    """Parse the JSON verdict from the LLM response.

    Returns True/False only for genuine bool values. Any parse error,
    missing key, or non-bool verdict → None (fail-open trigger).
    Note: isinstance(True, int) is True in Python, so we check bool
    explicitly and reject ints/strings.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "Self-RAG: LLM returned non-JSON (first 200 chars): %r", raw[:200]
        )
        return None
    verdict = data.get("verdict")
    if not isinstance(verdict, bool):
        logger.warning(
            "Self-RAG: LLM verdict is not a bool (got %r of type %s)",
            verdict,
            type(verdict).__name__,
        )
        return None
    reason = data.get("reason", "")
    if reason:
        logger.debug("Self-RAG judgment reason: %s", reason)
    return verdict
