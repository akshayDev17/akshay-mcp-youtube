"""Shared MCPServer instance; imported by every tools/*/tool.py for @app.tool() registration."""

from mcp.server import MCPServer

app = MCPServer(
    name="YouTube Analyzer & Uploader",
    instructions=(
        "Extract YouTube video metadata, transcripts, and comments. "
        "Comment tools return explicit paging state; loop on next_cursor "
        "until has_more is false. Super Thanks amounts are reported when present. "
        "Upload videos to the owner's configured channels with upload_yt_video or "
        "upload_yt_series: uploads are public by default (use visibility or "
        "publish_at to change that), run one at a time as server-side jobs, and "
        "report a job id to follow with get_yt_upload_status. If a channel needs "
        "signing in, a browser window opens on the owner's machine; tell the person "
        "to sign in there, then keep checking the job's status."
    ),
)
