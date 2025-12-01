"""PROMPTLINT MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from promptlint.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-promptlint[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-promptlint[mcp]'")
        return 1
    app = FastMCP("promptlint")

    @app.tool()
    def promptlint_scan(target: str) -> str:
        """Lint, version, and test prompts as code with a CI gate. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
