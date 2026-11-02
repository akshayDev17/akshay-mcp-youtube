"""MCP tool: create_yt_playlist — preview, then create, a playlist on a configured channel."""

from ..._app import app
from ...shared.logger import get_logger
from ...shared.upload import service, session, studio_playlist
from ...shared.upload.config import ConfigError
from ...shared.upload.playlist import build_playlist_spec, format_outcome, format_preview

logger = get_logger(__name__)


@app.tool(
    description=(
        "Create a playlist on one of the owner's configured YouTube channels, through YouTube "
        "Studio in the channel's signed-in browser profile. Before calling, settle three things "
        "with the user: (1) visibility — 'public', 'unlisted' or 'private'; there is NO default, "
        "so ask the user if they did not say; (2) name — if the user gave none, propose one and "
        "use it; (3) videos — the channel's own video ids (or links) in playlist order; if the "
        "user did not name the videos, ask which ones they want. Public, unlisted and private "
        "videos can all be added. Call first with preview=true (the default): it creates "
        "nothing, and lists each video's title and visibility in the planned order. Show that "
        "to the user and confirm the name, visibility and order; only after they confirm, call "
        "again with the same arguments and preview=false to create the playlist. The reply "
        "reads the created playlist back from Studio and reports status done, needs_attention "
        "(the playlist exists but something did not apply — fix it in Studio, do not create it "
        "again) or failed (nothing was created). A name the channel already uses is refused. "
        "Each video takes a few seconds; if the channel needs signing in, a browser window "
        "opens on the owner's machine and the call waits for them."
    ),
)
def create_yt_playlist(
    name: str,
    visibility: str,
    video_ids: list[str],
    channel: str | None = None,
    preview: bool = True,
) -> str:
    """
    Preview or create a playlist.

    Args:
        name: Playlist title (at most 150 characters). Propose one if the user gave none.
        visibility: 'public', 'unlisted' or 'private'. Required; ask the user if not stated.
        video_ids: The channel's video ids or video links, in playlist order.
        channel: Configured channel name or channel id; default channel if omitted.
        preview: True (default) only shows what would be created; False creates it.
    """
    params = {"name": name, "visibility": visibility, "video_ids": video_ids, "channel": channel}
    logger.info(f"MCP tool called: create_yt_playlist with {params}, preview={preview}")
    try:
        config = service.get_config()
        spec, problems = build_playlist_spec(params, config)
        if spec is None:
            return "Not created:\n" + "\n".join(f"- {p}" for p in problems)
        with studio_playlist.profile_lock(config):
            reason = session.ensure_session(
                spec.channel, config, lambda state, message: logger.info(f"playlist sign-in: {message or state}")
            )
            if reason:
                return f"Not created: the channel '{spec.channel.name}' is not signed in: {reason}"
            if preview:
                facts, problems = studio_playlist.preview(spec, config)
                return format_preview(spec, facts, problems)
            outcome = studio_playlist.create(spec, config)
        return format_outcome(spec, outcome)
    except studio_playlist.ProfileBusy as e:
        return f"Not created: {e}"
    except ConfigError as e:
        return f"Upload tools are not configured: {e}"
    except Exception as e:
        logger.error(f"Error in create_yt_playlist: {e}", exc_info=True)
        return f"Error creating playlist: {e}"
