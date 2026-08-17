"""
YouTube API utilities for fetching video information and transcripts.
"""

from .google_api import get_video_info, format_video_info
from .transcript_api import get_video_transcript
from .comments_api import (
    fetch_comments,
    nest_comments,
    get_comments_page,
    get_paid_comments,
)

# Re-export the functions for backward compatibility
__all__ = [
    'get_video_info',
    'get_video_transcript',
    'format_video_info',
    'fetch_comments',
    'nest_comments',
    'get_comments_page',
    'get_paid_comments',
]