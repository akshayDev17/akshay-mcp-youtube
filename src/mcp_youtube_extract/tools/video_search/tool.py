"""MCP tool: search_yt — full-length videos and playlists for a query."""

from ..._app import app
from ...shared.logger import get_logger
from ...shared.youtube.search import search_youtube, format_search_results

logger = get_logger(__name__)


@app.tool(
    description=(
        "Search YouTube and return two separate lists for one query: up to "
        "`limit` full-length videos, and up to `limit` playlists. Shorts are "
        "always excluded, identified by their /shorts/ url rather than by "
        "duration, so genuinely brief full videos are still returned. "
        "Channels are never returned. Sort with sort='relevance' (default), "
        "'date' for newest first, or 'views' for most-viewed first; sorting is "
        "applied by YouTube itself. Video results carry duration and view "
        "count; playlist ids can be passed straight to get_yt_playlist_info "
        "to check which of their videos are members-only. Note that search "
        "results do not carry publish timestamps, so sort='date' orders "
        "results without showing the dates."
    ),
)
def search_yt(query: str, limit: int = 10, sort: str = "relevance") -> str:
    """
    Search YouTube for full-length videos and playlists.

    Args:
        query: The search query, as typed into YouTube's search box.
        limit: Maximum results per category (videos and playlists each).
        sort: Result ordering — "relevance", "date", or "views".
    """
    logger.info(f"MCP tool called: search_yt with query={query!r}, sort={sort}")
    try:
        results = search_youtube(query, limit=limit, sort=sort)
        return format_search_results(results)
    except ValueError as e:
        logger.warning(f"Invalid search argument: {e}")
        return f"Invalid argument: {e}"
    except Exception as e:
        logger.error(f"Error searching for {query!r}: {e}", exc_info=True)
        return f"Error searching for {query!r}: {e}"
