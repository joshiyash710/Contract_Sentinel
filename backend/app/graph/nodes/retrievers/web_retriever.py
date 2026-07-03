"""
DuckDuckGo web-search fallback retriever for CRAG (Node 3).

web_search() NEVER raises — the exception boundary here is load-bearing:
spec §4.8 / AC-13 guarantee that any DDG failure (rate-limit, network error,
library rename, timeout) degrades to zero results, never a pipeline crash.

Timeout note (plan §2 / Risk table): unlike embed_query, there is no
client-level timeout for DDGS. The ThreadPoolExecutor future.result(timeout=…)
is the only bound, but a hung socket can leave the worker thread alive after
the timeout. To prevent the node from blocking at executor shutdown:
  - We do NOT use `with ThreadPoolExecutor(…)` (which calls shutdown(wait=True)).
  - Instead we submit the call, await with timeout, then shutdown(wait=False),
    abandoning any stuck worker thread so the node always returns promptly.
"""

import concurrent.futures
import logging

from app.graph.nodes.retrievers import RetrievalResult, make_snippet

logger = logging.getLogger("contractsentinel.crag_retrieval.web")

# Guarded import — library is being renamed to `ddgs` upstream (spec §4.8 pin).
# If both fail, DDGS=None and web_search degrades to zero results.
try:
    from duckduckgo_search import DDGS  # type: ignore[import-untyped]
except ImportError:
    try:
        from ddgs import DDGS  # type: ignore[import-untyped]
    except ImportError:
        DDGS = None  # type: ignore[assignment,misc]

_DDGS_UNAVAILABLE_WARNED = False


def web_search(query: str, max_results: int, timeout_seconds: int) -> RetrievalResult:
    """Search the web via DuckDuckGo for legal evidence on a clause.

    Returns RetrievalResult(snippets=up to max_results snippets in 001 shape,
    top_score=None). On ANY failure returns ([], None). Never raises (AC-13).
    """
    global _DDGS_UNAVAILABLE_WARNED

    if DDGS is None:
        if not _DDGS_UNAVAILABLE_WARNED:
            logger.warning(
                "web_search: duckduckgo_search / ddgs library not available; web fallback disabled"
            )
            _DDGS_UNAVAILABLE_WARNED = True
        return RetrievalResult(snippets=[], top_score=None)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_run_search, query, max_results)
        try:
            snippets = future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "web_search: timed out after %ds for query %.80r",
                timeout_seconds,
                query,
            )
            snippets = []
        except Exception as exc:
            logger.warning("web_search: error for query %.80r: %s", query, exc)
            snippets = []
    finally:
        # Non-blocking shutdown: don't wait for a stuck socket worker (plan §2).
        executor.shutdown(wait=False)

    return RetrievalResult(snippets=snippets, top_score=None)


def _run_search(query: str, max_results: int) -> list:
    """Execute the DDG search and map results to the 001-schema snippet shape.

    Called inside a ThreadPoolExecutor worker. May raise — caller catches all.
    """
    snippets = []
    count = 0
    try:
        results = DDGS().text(query, max_results=max_results)
        for r in results:
            if count >= max_results:
                break
            body = r.get("body", "")
            href = r.get("href", "")
            if not body or not href:
                continue  # skip malformed results (protects AC-6)
            snippets.append(make_snippet(body, href))
            count += 1
    except Exception as exc:
        logger.warning("web_search: DDG call failed: %s", exc)
        # Return whatever we collected so far (may be empty)
    return snippets
