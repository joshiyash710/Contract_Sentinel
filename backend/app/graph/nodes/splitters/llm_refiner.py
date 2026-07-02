"""
LLM-based clause boundary refiner for ClauseSplitterAgent (steps 2+3 of 3).

Uses Qwen3 14B via the ollama Python client.
Never raises — all failures fall back to returning regex_clauses unchanged.
"""

import concurrent.futures
import json
import logging

import httpx
import ollama

from app.graph.nodes.splitters import ClauseBoundary
from app.graph.state import ClauseType

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
        future = executor.submit(_call_ollama, regex_clauses, model_name, timeout_seconds)
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
    prompt = _LLM_PROMPT.format(clauses_json=clauses_json)

    client = ollama.Client(timeout=timeout_seconds)
    response = client.chat(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"num_predict": 4096},
    )
    raw_content = response["message"]["content"]
    return _parse_response(raw_content, regex_clauses)


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
        raise ValueError("LLM returned empty clauses list, falling back to regex output")

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
