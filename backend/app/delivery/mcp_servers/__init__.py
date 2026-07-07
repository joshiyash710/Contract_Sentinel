"""
app.delivery.mcp_servers — Drive and Gmail MCP servers.

Each server wraps google-api-python-client behind an MCP stdio interface.
Constitution §2 permanently permits only Drive + Gmail MCP integrations.
OAuth credential loading lives here at the server boundary (D10).
"""
