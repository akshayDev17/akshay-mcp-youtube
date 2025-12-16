"""
YouTube MCP Server

A simple MCP server that fetches YouTube video information and transcripts.
"""

import os
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types
from .youtube import get_video_info, get_video_transcript, format_video_info
from .logger import get_logger

logger = get_logger(__name__)

# Create the MCP server
server = Server("YouTube Video Analyzer")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="get_yt_video_info",
            description="Fetch YouTube video information and transcript.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "The YouTube video ID"
                    }
                },
                "required": ["video_id"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""
    if name != "get_yt_video_info":
        raise ValueError(f"Unknown tool: {name}")

    if not arguments or "video_id" not in arguments:
        raise ValueError("Missing 'video_id' argument")

    video_id = arguments["video_id"]
    logger.info(f"MCP tool called: get_yt_video_info with video_id: {video_id}")
    
    # yt-info-extract doesn't require API key, but keep API key optional for compatibility
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    
    result = []
    
    try:
        # Get video information
        logger.info(f"Processing video: {video_id}")
        video_info = get_video_info(api_key, video_id)
        result.append("=== VIDEO INFORMATION ===")
        result.append(format_video_info(video_info))
        result.append("")
        
        # Get transcript
        transcript = get_video_transcript(video_id)
        result.append("=== TRANSCRIPT ===")
        if transcript and not transcript.startswith("Transcript error:") and not transcript.startswith("Could not retrieve"):
            result.append(transcript)
            logger.info(f"Successfully processed video {video_id} with transcript")
        else:
            if transcript and (transcript.startswith("Transcript error:") or transcript.startswith("Could not retrieve")):
                result.append(f"Transcript issue: {transcript}")
                logger.warning(f"Transcript issue for video {video_id}: {transcript}")
            else:
                result.append("No transcript available for this video.")
                logger.warning(f"Video {video_id} processed but no transcript available")
        
        final_result = "\n".join(result)
        logger.debug(f"Tool execution completed for video {video_id}, result length: {len(final_result)} characters")
        
        return [types.TextContent(type="text", text=final_result)]
        
    except Exception as e:
        logger.error(f"Error processing video {video_id}: {e}", exc_info=True)
        return [types.TextContent(type="text", text=f"Error processing video {video_id}: {str(e)}")]

async def run():
    """Run the server using stdin/stdout streams."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

def main():
    """Main entry point for the MCP server."""
    logger.info("Starting YouTube MCP Server")
    try:
        asyncio.run(run())
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()
