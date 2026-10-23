# MCP YouTube Extract

[![PyPI version](https://badge.fury.io/py/mcp-youtube-extract.svg)](https://badge.fury.io/py/mcp-youtube-extract)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A Model Context Protocol (MCP) server for YouTube operations, demonstrating core MCP concepts including tools and logging.

**✨ No API Key Required!** Works out of the box using yt-info-extract for video metadata and yt-ts-extract for transcripts.

## Features

- **MCP Server**: A fully functional MCP server with:
  - **Tools**: Extract information from YouTube videos including metadata and transcripts
  - **Comprehensive Logging**: Detailed logging throughout the application
  - **Error Handling**: Robust error handling with fallback logic for transcripts
- **YouTube Integration**: Built-in YouTube capabilities using yt-info-extract and yt-ts-extract:
  - Extract video information (title, description, channel, publish date, view count)
  - Get video transcripts with intelligent fallback logic
  - Support for both manually created and auto-generated transcripts
  - No API key required for basic functionality

## 📦 Available on PyPI

This package is now available on PyPI! You can install it directly with:

```bash
pip install mcp-youtube-extract
```

Visit the package page: [mcp-youtube-extract on PyPI](https://pypi.org/project/mcp-youtube-extract/)

## Installation

### Quick Start (Recommended)

The easiest way to get started is to install from PyPI:

```bash
pip install mcp-youtube-extract
```

Or using pipx (recommended for command-line tools):

```bash
pipx install mcp-youtube-extract
```

This will install the latest version with all dependencies. You can then run the MCP server directly:

```bash
mcp_youtube_extract
```

### Using uv (Development)

For development or if you prefer uv:

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install the project
git clone https://github.com/sinjab/mcp_youtube_extract.git
cd mcp_youtube_extract

# Install dependencies (including dev dependencies)
uv sync --dev

# Set up your API key for development
cp .env.example .env
# Edit .env and add your YouTube API key
```

### From source

1. Clone the repository:
   ```bash
   git clone https://github.com/sinjab/mcp_youtube_extract.git
   cd mcp_youtube_extract
   ```

2. Install in development mode:
   ```bash
   uv sync --dev
   ```

## Configuration

### Environment Variables

**No configuration required!** The server works out of the box using yt-info-extract for metadata extraction.

**Optional:** For enhanced functionality, you can optionally set a YouTube API key:

```bash
# Optional YouTube API Configuration
YOUTUBE_API_KEY=your_youtube_api_key_here
```

**Optional:**
- `YOUTUBE_API_KEY`: Your YouTube Data API key (optional, provides additional fallback for metadata extraction)

### Getting Your YouTube API Key (Optional)

While not required, you can optionally set up a YouTube Data API key for enhanced functionality. Here's how to get one:

#### Step 1: Create a Google Cloud Project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" at the top of the page
3. Click "New Project" and give it a name (e.g., "MCP YouTube Extract")
4. Click "Create"

#### Step 2: Enable the YouTube Data API

1. In your new project, go to the [API Library](https://console.cloud.google.com/apis/library)
2. Search for "YouTube Data API v3"
3. Click on it and then click "Enable"

#### Step 3: Create API Credentials

1. Go to the [Credentials page](https://console.cloud.google.com/apis/credentials)
2. Click "Create Credentials" and select "API Key"
3. Your new API key will be displayed - copy it immediately
4. Click "Restrict Key" to secure it (recommended)

#### Step 4: Restrict Your API Key (Recommended)

1. In the API key settings, click "Restrict Key"
2. Under "API restrictions", select "Restrict key"
3. Choose "YouTube Data API v3" from the dropdown
4. Click "Save"

#### Step 5: Set Up Billing (Required)

1. Go to the [Billing page](https://console.cloud.google.com/billing)
2. Link a billing account to your project
3. **Note**: YouTube Data API has a free tier of 10,000 units per day, which is typically sufficient for most use cases

#### API Key Usage Limits

- **Free Tier**: 10,000 units per day
- **Cost**: $5 per 1,000 units after free tier
- **Note**: API key is only used as a fallback when yt-info-extract fails
- Most users won't need an API key as yt-info-extract handles most requests

#### Security Best Practices

- **Never commit your API key** to version control
- **Use environment variables** as shown in the configuration section
- **Restrict your API key** to only the YouTube Data API
- **Monitor usage** in the Google Cloud Console

## Usage

### Running the MCP Server

#### Using PyPI Installation (Recommended)

```bash
# Install from PyPI
pip install mcp-youtube-extract

# Run the server
mcp_youtube_extract
```

#### Using Development Setup

```bash
# Using uv
uv run mcp_youtube_extract

# Or directly
python -m mcp_youtube_extract.server
```

### Running Tests

```bash
# Run all pytest tests
uv run pytest

# Run specific pytest test
uv run pytest tests/test_with_api_key.py

# Run tests with coverage
uv run pytest --cov=src/mcp_youtube_extract --cov-report=term-missing
```

**Note**: The `tests/` directory contains 4 files:
- `test_context_fix.py` - Pytest test for context API fallback functionality
- `test_with_api_key.py` - Pytest test for full functionality with API key  
- `test_youtube_unit.py` - **Unit tests** for core YouTube functionality
- `test_inspector.py` - **Standalone inspection script** (not a pytest test)

**Test Coverage**: The project currently has 62% overall coverage with excellent coverage of core functionality:
- `youtube.py`: 81% coverage (core business logic)
- `logger.py`: 73% coverage (logging utilities)
- `server.py`: 22% coverage (MCP protocol handling)
- `__init__.py`: 100% coverage (package initialization)

### Running the Inspection Script

The `test_inspector.py` file is a standalone script that connects to the MCP server and validates its functionality:

```bash
# Run the inspection script to test server connectivity and functionality
uv run python tests/test_inspector.py
```

This script will:
- Connect to the MCP server
- List available tools, resources, and prompts
- Test the `get_yt_video_info` tool with a sample video
- Validate that the server is working correctly

### Using the YouTube Tool

The server provides one main tool: `get_yt_video_info`

This tool takes a YouTube video ID and returns:
- Video metadata (title, description, channel, publish date, view count) via yt-info-extract
- Video transcript (with fallback logic for different transcript types) via yt-ts-extract

**Example Usage:**
```python
# Extract video ID from YouTube URL: https://www.youtube.com/watch?v=dQw4w9WgXcQ
video_id = "dQw4w9WgXcQ"
result = get_yt_video_info(video_id)
```

### Client Configuration

To use this MCP server with a client, add the following configuration to your client's settings:

#### Using PyPI Installation (Recommended)

```json
{
  "mcpServers": {
    "mcp_youtube_extract": {
      "command": "mcp_youtube_extract"
    }
  }
}
```

**With optional API key:**
```json
{
  "mcpServers": {
    "mcp_youtube_extract": {
      "command": "mcp_youtube_extract",
      "env": {
        "YOUTUBE_API_KEY": "your_youtube_api_key"
      }
    }
  }
}
```

#### Using Development Setup

```json
{
  "mcpServers": {
    "mcp_youtube_extract": {
      "command": "uv",
      "args": [
        "--directory",
        "<your-project-directory>",
        "run",
        "mcp_youtube_extract"
      ]
    }
  }
}
```

**With optional API key:**
```json
{
  "mcpServers": {
    "mcp_youtube_extract": {
      "command": "uv",
      "args": [
        "--directory",
        "<your-project-directory>",
        "run",
        "mcp_youtube_extract"
      ],
      "env": {
        "YOUTUBE_API_KEY": "your_youtube_api_key"
      }
    }
  }
}
```

## Uploading to your channels

Three tools upload videos to channels you own: `upload_yt_video` (one video),
`upload_yt_series` (a batch, as a background job) and `get_yt_upload_status` (follow a
job). They drive YouTube Studio's own upload dialog in a dedicated Brave profile per
channel, logged in once. This is a bridge until the Google Cloud project passes YouTube's
API audit; automating Studio is outside YouTube's terms, so the channel carries that risk
until an official Data API backend replaces it.

**Uploads are public by default.** Pass `visibility` (`private`, `unlisted`) or
`publish_at` (ISO 8601 with a UTC offset) to change that.

### Configuration

| Variable | Default | |
|---|---|---|
| `YT_UPLOAD_CHANNELS` | required | `name=channel_id` pairs, e.g. `main=UCDzx6hNPpuha4fCwYA5WAyg,second=UC…` |
| `YT_UPLOAD_DEFAULT_CHANNEL` | first listed | channel used when a call names none |
| `YT_UPLOAD_BROWSER` | `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser` | must be the browser that created the profiles |
| `YT_UPLOAD_HEADLESS` | `true` | `false` shows the browser, for debugging |
| `YT_UPLOAD_LOGIN_TIMEOUT` | `600` | seconds a job waits for you to sign in |
| `YT_UPLOAD_CALL_WAIT` | `600` | seconds `upload_yt_video` waits before handing back a job id |

```bash
claude mcp add-json mcp_youtube_extract '{"command":"uv","args":["--directory","<repo>","run","mcp_youtube_extract"],"env":{"YT_UPLOAD_CHANNELS":"main=UCDzx6hNPpuha4fCwYA5WAyg"}}'
```

Everything lives under `~/.mcp-youtube-extract/`: `profiles/<name>/` (one Brave profile
per channel, mode 700), `jobs/` (job state) and `failures/` (a screenshot and the page
text for any failed step).

### Signing in

Nothing to do up front: the first upload to a channel that is not signed in opens a
normal Brave window on that channel's profile. Sign in with the channel's Google account
there; the server notices, closes the window and carries on. To sign in ahead of time:

```bash
uv run mcp_youtube_extract --login main
```

### Video folders

`folder` takes the explainer-video pipeline's layout: exactly one `.mp4`, `title.txt`
(first line), `description.md` (used verbatim, chapters included), `captions.srt` and
`thumbnail.png` / `thumbnail.jpg`. Explicit parameters override the folder.

Studio's upload dialog sets only the video's spoken language and adds captions in that
language, so `language` and `captions_language` must match `audio_language`.

### Jobs

Uploads run one at a time across all channels. A batch pauses a random 1–10 minutes
between uploads, skips entries that are invalid or fail, and reports them at the end.
Each video ends `done`, `needs_attention` (it exists on the channel but something did not
apply — never re-uploaded) or `failed` (nothing was created). Re-uploading the same file
to the same channel within 24 hours is refused. If the server stops mid-job, the job is
marked `interrupted`; `upload_yt_series(resume_job_id=…)` finishes it.

### Live tests

`tests/live/` uploads real private (or unlisted) test videos and prints each id to delete
in Studio. They run only with `YT_UPLOAD_LIVE_TESTS=1` and the `YT_UPLOAD_*` variables set.
YouTube caps daily uploads on channels without the one-time upload verification.

## Development

### Project Structure

```
mcp_youtube_extract/
├── src/
│   └── mcp_youtube_extract/
│       ├── __init__.py
│       ├── server.py          # MCP server implementation
│       ├── google_api.py      # yt-info-extract integration
│       ├── transcript_api.py  # yt-ts-extract integration
│       ├── youtube.py         # Unified API facade
│       └── logger.py          # Logging configuration
├── tests/
│   ├── __init__.py
│   ├── test_context_fix.py    # Context API fallback tests
│   ├── test_inspector.py      # Server inspection tests
│   ├── test_with_api_key.py   # Full functionality tests
│   └── test_youtube_unit.py   # Unit tests for core functionality
├── logs/                      # Application logs
├── .env                       # Environment variables (create from .env.example)
├── .gitignore                 # Git ignore rules (includes coverage files)
├── pyproject.toml
├── LICENSE                    # MIT License
└── README.md
```

### Testing Strategy

The project uses a comprehensive testing approach:

1. **Unit Tests** (`test_youtube_unit.py`): Test core YouTube functionality with mocked yt-info-extract
2. **Integration Tests** (`test_context_fix.py`, `test_with_api_key.py`): Test full server functionality
3. **Manual Validation** (`test_inspector.py`): Interactive server inspection tool

### Error Handling

The project includes robust error handling:
- **Graceful extraction failures**: Returns appropriate error messages instead of crashing
- **Multiple fallback strategies**: yt-info-extract provides automatic fallback between YouTube Data API, yt-dlp, and pytubefix
- **Transcript fallback logic**: Multiple strategies for transcript retrieval via yt-ts-extract
- **Consistent error responses**: Standardized error message format
- **Comprehensive logging**: Detailed logs for debugging and monitoring

### Building

```bash
# Install build dependencies
uv add --dev hatch

# Build the package
uv run hatch build
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Getting Started

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Support

If you encounter any issues or have questions, please:
1. Check the [existing issues](https://github.com/sinjab/mcp_youtube_extract/issues)
2. Create a new issue with detailed information about your problem
3. Include logs and error messages when applicable
