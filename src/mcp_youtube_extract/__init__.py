"""
MCP YouTube Extract - A Model Context Protocol server for YouTube operations
"""

from .shared.logger import get_logger
from .server import main
from .shared.youtube.metadata import get_video_info, format_video_info
from .shared.youtube.transcript import get_video_transcript

logger = get_logger(__name__)

__version__ = "0.1.0"

logger.info(f"MCP YouTube Extract package initialized, version: {__version__}")

__all__ = [
    "main",
    "get_video_info",
    "get_video_transcript", 
    "format_video_info",
]
