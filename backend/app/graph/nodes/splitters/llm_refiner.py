"""
LLM-based clause boundary refiner for ClauseSplitterAgent (steps 2+3 of 3).

Uses Qwen3 14B via the ollama Python client.
Never raises — all failures fall back to returning regex_clauses unchanged.
"""

import concurrent.futures
import json
import logging

import httpx

from app.llm.chat_client import get_chat_client  # feature 046: provider seam (ollama default | groq)

from app.graph.nodes.splitters import ClauseBoundary
from app.graph.state import ClauseType
from app.llm import prompt_guard

import app.config as _config

# Read by bare name below (never via _config.NAME) so tests monkeypatch the node-module attr
# — feature 028 determinism sampling options; mirrors the 027 alias pattern.
OLLAMA_TEMPERATURE = _config.OLLAMA_TEMPERATURE
OLLAMA_SEED = _config.OLLAMA_SEED
CLAUSE_SPLITTER_LLM_EMIT_TEXT = _config.CLAUSE_SPLITTER_LLM_EMIT_TEXT  # feature 029 Lever F
CLAUSE_SPLITTER_LLM_NUM_PREDICT = _config.CLAUSE_SPLITTER_LLM_NUM_PREDICT  # feature 029 Lever F

logger = logging.getLogger("contractsentinel.clause_splitter.llm_refiner")

_VALID_CLAUSE_TYPES = {ct.value for ct in ClauseType}

_LLM_PROMPT = """You are a contract clause analysis assistant. You are given a list of clause segments
that were detected by a regex-based pre-pass on a legal contract. Your job is to:

1. REVIEW the clause boundaries. Merge fragments that belong to the same logical clause.
   Split any run-on segments that contain multiple distinct clauses.
2. CLASSIFY each clause into one of these types: "definitions", "payment", "delivery",
   "term", "termination", "confidentiality", "intellectual_property", "liability",
   "force_majeure", "dispute_resolution", "general", "other".
   If you cannot confidently classify a clause, set clause_type to null.

Respond with ONLY a JSON object matching this exact schema — no markdown, no explanation:

{{
  "clauses": [
    {{
      "text": "The full text of the clause",
      "section_number": "1.2" or null,
      "clause_type": "one of the types listed above" or null
    }}
  ]
}}

Rules:
- Preserve ALL original text — do not rewrite, summarize, or omit any clause content.
- Maintain the original document order.
- Every piece of input text must appear in exactly one output clause.
- If a clause has a section number (e.g. "1.2", "Article 5", "§3"), include it.
  If it has no section marker, set section_number to null.
- If you are uncertain about the clause_type, set it to null rather than guessing.

Here are the regex-detected clause segments:

{clauses_json}
"""

_GROUPING_PROMPT = """You are a contract clause analysis assistant. You are given a numbered list of
clause segments detected by a regex-based pre-pass on a legal contract. Your job is to:

1. GROUP the segments into logical clauses by referencing their "index" numbers. Merge segments that
   belong to the same logical clause by listing their indices together. Do NOT rewrite or emit any
   clause text — reference indices only.
2. CLASSIFY each grouped clause into one of these types: "definitions", "payment", "delivery",
   "term", "termination", "confidentiality", "intellectual_property", "liability", "force_majeure",
   "dispute_resolution", "general", "other". If you cannot confidently classify, use null.

Respond with ONLY a JSON object matching this exact schema — no markdown, no explanation, NO clause text:

{{
  "clauses": [
    {{
      "indices": [1, 2],
      "section_number": "1.2" or null,
      "clause_type": "one of the types listed above" or null
    }}
  ]
}}

Rules:
- Every input index must appear in EXACTLY ONE output clause.
- Maintain the original document order (indices ascending overall, no gaps, no duplicates).
- Do NOT split a segment — a segment index belongs wholly to one output clause.
- If a clause has a section number, include it; otherwise set section_number to null.
- If uncertain about the clause_type, set it to null rather than guessing.

Here are the regex-detected clause segments:

{clauses_json}
"""

# ── Feature 035: system-message instruction blocks (ON path). The untrusted serialized segments move
# to the wrapped user_body; the original _LLM_PROMPT/_GROUPING_PROMPT are used UNCHANGED on the OFF
# path (byte-identical, AC-7). Used raw (not .format()ed) → single braces in the JSON schema example.
_LLM_SYSTEM = """You are a contract clause analysis assistant. You are given a list of clause segments
that were detected by a regex-based pre-pass on a legal contract. Your job is to:

1. REVIEW the clause boundaries. Merge fragments that belong to the same logical clause.
   Split any run-on segments that contain multiple distinct clauses.
2. CLASSIFY each clause into one of these types: "definitions", "payment", "delivery",
   "term", "termination", "confidentiality", "intellectual_property", "liability",
   "force_majeure", "dispute_resolution", "general", "other".
   If you cannot confidently classify a clause, set clause_type to null.

Respond with ONLY a JSON object matching this exact schema — no markdown, no explanation:

{
  "clauses": [
    {
      "text": "The full text of the clause",
      "section_number": "1.2" or null,
      "clause_type": "one of the types listed above" or null
    }
  ]
}

Rules:
- Preserve ALL original text — do not rewrite, summarize, or omit any clause content.
- Maintain the original document order.
- Every piece of input text must appear in exactly one output clause.
- If a clause has a section number (e.g. "1.2", "Article 5", "§3"), include it.
  If it has no section marker, set section_number to null.
- If you are uncertain about the clause_type, set it to null rather than guessing."""

_GROUPING_SYSTEM = """You are a contract clause analysis assistant. You are given a numbered list of
clause segments detected by a regex-based pre-pass on a legal contract. Your job is to:

1. GROUP the segments into logical clauses by referencing their "index" numbers. Merge segments that
   belong to the same logical clause by listing their indices together. Do NOT rewrite or emit any
   clause text — reference indices only.
2. CLASSIFY each grouped clause into one of these types: "definitions", "payment", "delivery",
   "term", "termination", "confidentiality", "intellectual_property", "liability", "force_majeure",
   "dispute_resolution", "general", "other". If you cannot confidently classify, use null.

Respond with ONLY a JSON object matching this exact schema — no markdown, no explanation, NO clause text:

{
  "clauses": [
    {
      "indices": [1, 2],
      "section_number": "1.2" or null,
      "clause_type": "one of the types listed above" or null
    }
  ]
}

Rules:
- Every input index must appear in EXACTLY ONE output clause.
- Maintain the original document order (indices ascending overall, no gaps, no duplicates).
- Do NOT split a segment — a segment index belongs wholly to one output clause.
- If a clause has a section number, include it; otherwise set section_number to null.
- If uncertain about the clause_type, set it to null rather than guessing."""


def refine_with_llm(
    regex_clauses: list,
    timeout_seconds: int,
    model_name: str,
) -> list:
    """Refine regex-detected boundaries via Qwen3 14B (Ollama). Never raises —
    all failures fall back to returning regex_clauses unchanged.
    """
    result = regex_clauses
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _call_ollama, regex_clauses, model_name, timeout_seconds
        )
        try:
            result = future.result(timeout=timeout_seconds)
        except (concurrent.futures.TimeoutError, httpx.TimeoutException):
            logger.warning(
                "LLM refinement timed out after %ds, using regex-only output",
                timeout_seconds,
            )
        except Exception:
            logger.warning(
                "LLM refinement failed, using regex-only output", exc_info=True
            )
    return result


def _call_ollama(regex_clauses: list, model_name: str, timeout_seconds: int) -> list:
    """Submit clauses to Ollama and parse/validate the response.

    Raises on any error so the caller's except block can fall back.
    """
    clauses_json = json.dumps(
        [
            {
                "index": c.position,
                "section_number": c.section_number,
                "text": c.text,
            }
            for c in regex_clauses
        ],
        ensure_ascii=False,
        indent=2,
    )

    # Lever F (feature 029): grouping mode returns index-grouping + type metadata only (no
    # full text re-emit), with a smaller output-token cap. EMIT_TEXT=True is the reversible
    # pre-029 path (re-emit full text, num_predict 4096).
    if CLAUSE_SPLITTER_LLM_EMIT_TEXT:
        legacy = _LLM_PROMPT.format(clauses_json=clauses_json)
        system = _LLM_SYSTEM
        num_predict = 4096
    else:
        legacy = _GROUPING_PROMPT.format(clauses_json=clauses_json)
        system = _GROUPING_SYSTEM
        num_predict = CLAUSE_SPLITTER_LLM_NUM_PREDICT

    # Feature 035: wrap the untrusted serialized segments; OFF path uses `legacy` unchanged (AC-7).
    user_body = prompt_guard.wrap_block(
        "Here are the regex-detected clause segments:", clauses_json, "SEGMENTS"
    )
    messages = prompt_guard.build_messages(system, user_body, legacy)

    client = get_chat_client(timeout_seconds)
    response = client.chat(
        model=model_name,
        messages=messages,
        format="json",
        think=False,  # qwen3 thinking mode + format="json" wastes the token budget
        # on hidden reasoning and blows the timeout; the JSON answer never needs it.
        options={
            "num_predict": num_predict,
            "temperature": OLLAMA_TEMPERATURE,
            **({"seed": OLLAMA_SEED} if OLLAMA_SEED is not None else {}),
        },
    )
    raw_content = response["message"]["content"]
    if CLAUSE_SPLITTER_LLM_EMIT_TEXT:
        return _parse_response(raw_content, regex_clauses)
    return _parse_grouping_response(raw_content, regex_clauses)


def _parse_response(raw_content: str, regex_clauses: list) -> list:
    """Parse and validate the LLM JSON response, returning refined ClauseBoundary list.

    Raises ValueError on any validation failure so the caller falls back.
    """
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON (first 500 chars): {raw_content[:500]!r}"
        ) from exc

    if "clauses" not in data or not isinstance(data["clauses"], list):
        raise ValueError(
            f"LLM response missing 'clauses' list (first 500 chars): {raw_content[:500]!r}"
        )

    if not data["clauses"]:
        raise ValueError(
            "LLM returned empty clauses list, falling back to regex output"
        )

    refined = []
    for i, item in enumerate(data["clauses"], start=1):
        text = item.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"LLM response clause {i} has empty/missing 'text': {item!r}"
            )
        raw_type = item.get("clause_type")
        validated_type = (
            raw_type
            if (raw_type is not None and raw_type in _VALID_CLAUSE_TYPES)
            else None
        )

        refined.append(
            ClauseBoundary(
                clause_id=f"clause_{i:03d}",
                text=text,
                position=i,
                section_number=item.get("section_number"),
                clause_type=validated_type,
            )
        )

    input_chars = sum(len(c.text) for c in regex_clauses)
    output_chars = sum(len(b.text) for b in refined)
    if input_chars > 0 and output_chars < input_chars * 0.5:
        raise ValueError(
            f"LLM dropped too much text: output {output_chars} chars vs "
            f"input {input_chars} chars, falling back to regex output"
        )

    return refined


def _parse_grouping_response(raw_content: str, regex_clauses: list) -> list:
    """Parse the Lever F grouping response (index-grouping + type, NO text) and
    reassemble each clause's text locally from the regex segments.

    Raises ValueError on any validation failure so the caller falls back to regex output.
    The text-preservation guarantee is structural: the flattened output indices must be an
    exact ordered partition of [1..N] (every input segment used once, ascending), so
    reassembling by joining the referenced segments reproduces every segment exactly.
    """
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON (first 500 chars): {raw_content[:500]!r}"
        ) from exc

    if "clauses" not in data or not isinstance(data["clauses"], list):
        raise ValueError(
            f"LLM response missing 'clauses' list (first 500 chars): {raw_content[:500]!r}"
        )
    if not data["clauses"]:
        raise ValueError("LLM returned empty clauses list, falling back to regex output")

    n = len(regex_clauses)
    by_index = {c.position: c for c in regex_clauses}

    flat: list = []
    groups: list = []
    for i, item in enumerate(data["clauses"], start=1):
        indices = item.get("indices")
        if not isinstance(indices, list) or not indices:
            raise ValueError(f"grouping clause {i} has missing/empty 'indices': {item!r}")
        if not all(isinstance(x, int) for x in indices):
            raise ValueError(f"grouping clause {i} has non-int index: {indices!r}")
        flat.extend(indices)
        groups.append((indices, item))

    # Exact ordered partition of [1..N]: each input index once, ascending, no gaps/dupes.
    if flat != list(range(1, n + 1)):
        raise ValueError(
            f"grouping indices are not an exact ordered partition of 1..{n}: {flat!r}"
        )

    refined = []
    for k, (indices, item) in enumerate(groups, start=1):
        segments = [by_index[idx] for idx in indices]
        text = "\n".join(s.text for s in segments)
        raw_section = item.get("section_number")
        section_number = (
            raw_section
            if isinstance(raw_section, str) and raw_section.strip()
            else segments[0].section_number
        )
        raw_type = item.get("clause_type")
        validated_type = (
            raw_type
            if (raw_type is not None and raw_type in _VALID_CLAUSE_TYPES)
            else None
        )
        refined.append(
            ClauseBoundary(
                clause_id=f"clause_{k:03d}",
                text=text,
                position=k,
                section_number=section_number,
                clause_type=validated_type,
            )
        )

    return refined
