"""
Integration tests for CORS headers (spec D7 / AC-23).

TDD red phase: all tests FAIL (ImportError) until Task 19 implements create_app.
Run: python -m pytest tests/integration/test_api_cors.py -v
"""


def test_preflight_allowed_origin_gets_header(client):
    """OPTIONS from http://localhost:5173 → Access-Control-Allow-Origin present (AC-23)."""
    r = client.options(
        "/api/analyze",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    # CORSMiddleware returns 200 for preflight (or 400 if the route does not exist as OPTIONS)
    # The key assertion is the presence of the ACAO header
    assert "access-control-allow-origin" in r.headers


def test_disallowed_origin_no_header(client):
    """An origin absent from the allowlist → no Access-Control-Allow-Origin header (AC-23)."""
    r = client.options(
        "/api/analyze",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in r.headers
