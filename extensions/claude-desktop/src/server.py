"""Claude Desktop extension entry point for the packaged UsageTrim MCP server."""

from usagetrim.mcp.server import run_mcp_stdio_server

if __name__ == "__main__":
    run_mcp_stdio_server("desktop")
