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
from app.llm import prompt_guard

import app.config as _config

# Read by bare name below (never via _config.NAME) so tests monkeypatch the node-module attr
# — feature 028 determinism sampling options; mirrors the 027 alias pattern.
OLLAMA_TEMPERATURE = _config.OLLAMA_TEMPERATURE
OLLAMA_SEED = _config.OLLAMA_SEED
SELF_RAG_MERGED_NUM_PREDICT = _config.SELF_RAG_MERGED_NUM_PREDICT  # feature 029 Lever C

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

_COMBINED_PROMPT = """\
You are a contract-risk analysis assistant. Judge the following contract clause on THREE \
independent questions at once, using the clause text and the retrieved evidence:

1. "relevance": is the clause a SUBSTANTIVE, analyzable provision (obligations, rights, \
liabilities, deadlines, restrictions, IP assignment, termination rights)? true if substantive; \
false if boilerplate / structural filler (page header, pure definitions list, signature block, \
numbering-only text).
2. "isrel": is the retrieved evidence ON-TOPIC and RELEVANT to this clause? true if it directly \
addresses the legal issue the clause raises; false if off-topic, too generic, or about a different \
legal domain.
3. "issup": does the evidence SUPPORT flagging this clause as a concern worth surfacing to a \
reviewer (a material contractual risk — one-sided obligation, missing protection, unusual liability \
shift, IP assignment issue, punitive termination right)? true if it represents a meaningful risk; \
false if standard/balanced or unsupported.

Respond with ONLY a JSON object — no markdown, no explanation:
{{"relevance": true, "isrel": true, "issup": true, "reason": "<one short sentence>"}}

Each of the three values must be a JSON boolean (true or false).

Contract clause:
{clause_text}

Retrieved evidence:
{evidence_text}
"""


# ── Feature 035: system-message instruction blocks (ON path). Data headers move to the wrapped
# user_body; the original _*_PROMPT constants above are used UNCHANGED on the OFF path (byte-identical).
_RELEVANCE_SYSTEM = """\
You are a contract-risk analysis assistant. Your task is to decide whether the \
following contract clause is a SUBSTANTIVE provision — one that could plausibly \
carry a contractual concern worth evaluating (e.g. obligations, rights, \
liabilities, deadlines, restrictions, IP assignment, termination rights).

Respond with ONLY a JSON object — no markdown, no explanation:
{"verdict": true, "reason": "<one short sentence>"}

Set "verdict" to true if the clause IS a substantive, analyzable provision.
Set "verdict" to false if the clause is boilerplate / structural filler \
(e.g. a page header, a definitions list with no substantive content, a \
signature block, or blank / numbering-only text)."""

_ISREL_SYSTEM = """\
You are a contract-risk analysis assistant. Your task is to decide whether the \
retrieved evidence is ON-TOPIC and RELEVANT to the following contract clause.

Respond with ONLY a JSON object — no markdown, no explanation:
{"verdict": true, "reason": "<one short sentence>"}

Set "verdict" to true if the evidence directly addresses the legal issue \
raised by this clause (e.g. relevant case law, regulatory text, or market \
norms that bear on the clause's terms).
Set "verdict" to false if the evidence is off-topic, too generic, or \
clearly about a different legal domain than the clause."""

_ISSUP_WITH_EVIDENCE_SYSTEM = """\
You are a contract-risk analysis assistant. Your task is to decide whether \
the evidence SUPPORTS flagging this contract clause as a concern worth \
surfacing to a reviewer (i.e. the clause poses a material contractual risk).

Respond with ONLY a JSON object — no markdown, no explanation:
{"verdict": true, "reason": "<one short sentence>"}

Set "verdict" to true if the clause, in light of the evidence, represents \
a meaningful risk (one-sided obligation, missing protection, unusual liability \
shift, IP assignment issue, punitive termination right, etc.).
Set "verdict" to false if the clause appears standard/balanced or the \
evidence does not support flagging it."""

_ISSUP_TEXT_ONLY_SYSTEM = """\
You are a contract-risk analysis assistant. No retrieved evidence is available \
for this clause — judge SOLELY on the clause text itself.

Your task is to decide whether this contract clause on its own represents \
a material contractual risk worth surfacing to a reviewer.

Respond with ONLY a JSON object — no markdown, no explanation:
{"verdict": true, "reason": "<one short sentence>"}

Set "verdict" to true if the clause is self-evidently risky on its face \
(e.g. an uncapped liability cap, a unilateral termination right, a broad IP \
assignment, a forced-forum clause in an unfavourable jurisdiction).
Set "verdict" to false if the clause appears standard or low-risk."""

_COMBINED_SYSTEM = """\
You are a contract-risk analysis assistant. Judge the following contract clause on THREE \
independent questions at once, using the clause text and the retrieved evidence:

1. "relevance": is the clause a SUBSTANTIVE, analyzable provision (obligations, rights, \
liabilities, deadlines, restrictions, IP assignment, termination rights)? true if substantive; \
false if boilerplate / structural filler (page header, pure definitions list, signature block, \
numbering-only text).
2. "isrel": is the retrieved evidence ON-TOPIC and RELEVANT to this clause? true if it directly \
addresses the legal issue the clause raises; false if off-topic, too generic, or about a different \
legal domain.
3. "issup": does the evidence SUPPORT flagging this clause as a concern worth surfacing to a \
reviewer (a material contractual risk — one-sided obligation, missing protection, unusual liability \
shift, IP assignment issue, punitive termination right)? true if it represents a meaningful risk; \
false if standard/balanced or unsupported.

Respond with ONLY a JSON object — no markdown, no explanation:
{"relevance": true, "isrel": true, "issup": true, "reason": "<one short sentence>"}

Each of the three values must be a JSON boolean (true or false)."""


def _clause_body(clause_trunc: str) -> str:
    """user_body carrying only the wrapped clause (ON path)."""
    return prompt_guard.wrap_block("Contract clause:", clause_trunc, "CLAUSE")


def _clause_evidence_body(clause_trunc: str, evidence_str: str) -> str:
    """user_body carrying the wrapped clause + wrapped evidence (ON path)."""
    return (
        prompt_guard.wrap_block("Contract clause:", clause_trunc, "CLAUSE")
        + "\n\n"
        + prompt_guard.wrap_block("Retrieved evidence:", evidence_str, "EVIDENCE")
    )


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
    legacy = _RELEVANCE_PROMPT.format(clause_text=clause_trunc)
    messages = prompt_guard.build_messages(_RELEVANCE_SYSTEM, _clause_body(clause_trunc), legacy)
    return _run_judgment(messages, timeout_seconds, model_name)


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
    legacy = _ISREL_PROMPT.format(clause_text=clause_trunc, evidence_text=evidence_str)
    messages = prompt_guard.build_messages(
        _ISREL_SYSTEM, _clause_evidence_body(clause_trunc, evidence_str), legacy
    )
    return _run_judgment(messages, timeout_seconds, model_name)


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
        legacy = _ISSUP_TEXT_ONLY_PROMPT.format(clause_text=clause_trunc)
        messages = prompt_guard.build_messages(
            _ISSUP_TEXT_ONLY_SYSTEM, _clause_body(clause_trunc), legacy
        )
    else:
        remaining = max(0, prompt_max_chars - len(clause_trunc))
        evidence_str = format_evidence(evidence_snippets, remaining)
        legacy = _ISSUP_WITH_EVIDENCE_PROMPT.format(
            clause_text=clause_trunc, evidence_text=evidence_str
        )
        messages = prompt_guard.build_messages(
            _ISSUP_WITH_EVIDENCE_SYSTEM, _clause_evidence_body(clause_trunc, evidence_str), legacy
        )
    return _run_judgment(messages, timeout_seconds, model_name)


def check_combined(
    clause_text: str,
    evidence_snippets: Optional[List[Dict[str, Any]]],
    timeout_seconds: int,
    model_name: str,
    prompt_max_chars: int,
) -> Optional[dict]:
    """Lever C (feature 029): one combined judgment call returning all three verdicts
    (relevance + isrel + issup) for an evidence-present clause, instead of up to three
    sequential calls. Never raises.

    Contract (crisp AC-6 vs AC-7 boundary):
      - Returns None on a WHOLE-CALL failure — timeout / exception, non-JSON response,
        or JSON that is not an object. The caller applies the fail-open default.
      - Otherwise returns {"relevance": v, "isrel": v, "issup": v} where each v is a
        genuine bool if that key is present and boolean, else None (per-key missing /
        non-bool → that verdict is None; the caller applies existing per-verdict fail-open).
    """
    clause_trunc = clause_text[:prompt_max_chars]
    remaining = max(0, prompt_max_chars - len(clause_trunc))
    evidence_str = format_evidence(evidence_snippets, remaining)
    legacy = _COMBINED_PROMPT.format(clause_text=clause_trunc, evidence_text=evidence_str)
    messages = prompt_guard.build_messages(
        _COMBINED_SYSTEM, _clause_evidence_body(clause_trunc, evidence_str), legacy
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_combined, messages, timeout_seconds, model_name)
        try:
            return future.result(timeout=timeout_seconds)
        except (concurrent.futures.TimeoutError, httpx.TimeoutException):
            logger.warning(
                "Self-RAG combined judgment timed out after %ds", timeout_seconds
            )
            return None
        except Exception:
            logger.warning("Self-RAG combined judgment failed", exc_info=True)
            return None


def _call_combined(messages: list, timeout_seconds: int, model_name: str) -> Optional[dict]:
    """Perform the combined Ollama chat call and parse the 3-verdict object. Raises on
    transport error so the caller's except block returns None (whole-call failure)."""
    client = ollama.Client(timeout=timeout_seconds)
    response = client.chat(
        model=model_name,
        messages=messages,
        format="json",
        think=False,  # same rationale as _call_ollama
        options={
            "num_predict": SELF_RAG_MERGED_NUM_PREDICT,
            "temperature": OLLAMA_TEMPERATURE,
            **({"seed": OLLAMA_SEED} if OLLAMA_SEED is not None else {}),
        },
    )
    raw = response["message"]["content"]
    return _parse_combined(raw)


def _parse_combined(raw: str) -> Optional[dict]:
    """Parse the combined JSON object.

    None on whole-call failure (non-JSON, or not a JSON object). Otherwise a dict with
    each of relevance/isrel/issup a genuine bool or None (reject ints/strings — same
    discipline as _parse_verdict).
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "Self-RAG combined: LLM returned non-JSON (first 200 chars): %r", raw[:200]
        )
        return None
    if not isinstance(data, dict):
        logger.warning(
            "Self-RAG combined: LLM response is not a JSON object (got %s)",
            type(data).__name__,
        )
        return None
    result = {}
    for key in ("relevance", "isrel", "issup"):
        v = data.get(key)
        result[key] = v if isinstance(v, bool) else None
    reason = data.get("reason", "")
    if reason:
        logger.debug("Self-RAG combined judgment reason: %s", reason)
    return result


def _run_judgment(messages: list, timeout_seconds: int, model_name: str) -> Optional[bool]:
    """Submit a judgment message list to Ollama and parse the bool verdict.

    Uses ollama.Client(timeout=...) as the primary abort bound (kills the
    underlying httpx call so a hung socket cannot outlive the timeout),
    with ThreadPoolExecutor.future.result(timeout=...) as a backstop.
    Mirrors llm_refiner.py:67-80, 102-108. Never raises — all failures
    return None.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_ollama, messages, timeout_seconds, model_name)
        try:
            return future.result(timeout=timeout_seconds)
        except (concurrent.futures.TimeoutError, httpx.TimeoutException):
            logger.warning("Self-RAG LLM judgment timed out after %ds", timeout_seconds)
            return None
        except Exception:
            logger.warning("Self-RAG LLM judgment failed", exc_info=True)
            return None


def _call_ollama(messages: list, timeout_seconds: int, model_name: str) -> Optional[bool]:
    """Perform the Ollama chat call and parse the verdict. Raises on any error."""
    client = ollama.Client(timeout=timeout_seconds)
    response = client.chat(
        model=model_name,
        messages=messages,
        format="json",
        think=False,  # qwen3 thinking mode + format="json" wastes the token budget
        # on hidden reasoning and blows the timeout; the JSON answer never needs it.
        options={
            "num_predict": 256,
            "temperature": OLLAMA_TEMPERATURE,
            **({"seed": OLLAMA_SEED} if OLLAMA_SEED is not None else {}),
        },
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
