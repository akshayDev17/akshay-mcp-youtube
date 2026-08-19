"""Shared MCPServer instance; imported by every tools/*/tool.py for @app.tool() registration."""

from mcp.server import MCPServer

app = MCPServer(
    name="YouTube Video Analyzer",
    instructions=(
        "Extract YouTube video metadata, transcripts, and comments. "
        "Comment tools return explicit paging state; loop on next_cursor "
        "until has_more is false. Super Thanks amounts are reported when present."
    ),
)
