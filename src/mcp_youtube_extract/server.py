"""
YouTube MCP Server entry point.

The MCPServer instance lives in _app.py so it can be imported by every
tools/*/tool.py without circular-import risk. Importing each tool module here
runs its @app.tool() decorator, registering the tool.
"""

import asyncio

from ._app import app
from .shared.logger import get_logger

# Side-effect imports: each tool module registers itself with @app.tool() on import.
from .tools.video_info import tool as _video_info_tool  # noqa: F401
from .tools.video_comments import tool as _video_comments_tool  # noqa: F401
from .tools.paid_comments import tool as _paid_comments_tool  # noqa: F401
from .tools.super_thanks_summary import tool as _super_thanks_summary_tool  # noqa: F401

logger = get_logger(__name__)


def main():
    """Main entry point for the MCP server."""
    logger.info("Starting YouTube MCP Server")
    try:
        asyncio.run(app.run_stdio_async())
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
