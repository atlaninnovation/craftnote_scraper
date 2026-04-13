# Craftnote Scraper

Automated tool to download service report PDFs and spreadsheets (XLSX) from Craftnote project chats for wind turbine maintenance documentation.

## Problem Statement

Wind turbine service reports and maintenance spreadsheets are stored in Craftnote's project chat feature. While Craftnote provides a REST API, the chat messages endpoint requires "Advanced API access" which is not available with standard API keys. Files in the chat are only accessible through the web interface.

## Solution

A hybrid approach using:
1. **Craftnote API** - Enumerate projects, get metadata, build wind farm/turbine structure
2. **Playwright browser automation** - Login and download files from project chats
3. **Matrix room mapping** - Link Craftnote projects to Matrix room IDs for cross-referencing

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Data Flow                                     │
│                                                                       │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────────────┐ │
│  │ Craftnote   │     │ Playwright  │     │   Local Storage         │ │
│  │ API         │────▶│ Browser     │────▶│   downloads/            │ │
│  │ (metadata)  │     │ (files)     │     │   ├── {wind_farm}/      │ │
│  └─────────────┘     └─────────────┘     │   │   └── {turbine}/    │ │
│        │                   │              │   │       ├── *.pdf     │ │
│        │                   │              │   │       └── *.xlsx    │ │
│        ▼                   ▼              └─────────────────────────┘ │
│  - List projects     - Login to web app                               │
│  - Map structure     - Navigate to chat                               │
│  - Get metadata      - Download files                                 │
└──────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
craftnote_scraper/
├── src/
│   └── craftnote_scraper/
│       ├── __init__.py
│       ├── api/                    # Craftnote API client
│       │   ├── __init__.py
│       │   ├── client.py           # HTTP client wrapper
│       │   └── models.py           # Pydantic models for API responses
│       ├── scraper/                # Playwright browser automation
│       │   ├── __init__.py
│       │   ├── browser.py          # Browser session management
│       │   ├── login.py            # Authentication flow
│       │   └── downloader.py       # File download logic
│       ├── mapping/                # Project/Matrix mapping
│       │   ├── __init__.py
│       │   └── wind_farms.py       # Wind farm/turbine mapping
│       ├── storage/                # File organization
│       │   ├── __init__.py
│       │   └── organizer.py        # Download organization
│       └── cli.py                  # Command-line interface
├── tests/
│   ├── __init__.py
│   ├── test_api/
│   ├── test_scraper/
│   └── test_mapping/
├── pyproject.toml
├── .env.example
├── .gitignore
├── AGENTS.md
└── README.md
```

## Layer Architecture

Following AGENTS.md conventions, the codebase uses a layered architecture:

| Layer | Purpose | Dependencies |
|-------|---------|--------------|
| `api/models.py` | Pydantic models for API data | None (leaf module) |
| `api/client.py` | Craftnote API HTTP client | models |
| `mapping/wind_farms.py` | Wind farm/turbine/Matrix mapping | models |
| `scraper/browser.py` | Playwright browser management | None |
| `scraper/login.py` | Authentication flow | browser |
| `scraper/downloader.py` | File download logic | browser, login |
| `storage/organizer.py` | File organization | models, mapping |
| `cli.py` | Entry point | all above |

**Import rule**: Lower layers cannot import from higher layers.

## Data Models

### Wind Farm Structure

```python
@dataclass
class WindTurbine:
    craftnote_project_id: str
    name: str                    # e.g., "BO1 - 16562"
    matrix_room_id: str | None   # e.g., "!SQqWBcnerkrXAWzPKL:matrix.windreserve.de"

@dataclass  
class WindFarm:
    name: str                    # e.g., "Boddin"
    craftnote_folder_id: str
    matrix_space_id: str | None
    turbines: list[WindTurbine]
```

### Download Tracking

```python
@dataclass
class DownloadedFile:
    file_id: str
    filename: str
    file_type: Literal["pdf", "xlsx"]
    downloaded_at: datetime
    craftnote_project_id: str
    local_path: Path
    size_bytes: int
    checksum: str
```

## Configuration

Environment variables (`secrets.env`):

```bash
# Craftnote API
# Copy .env.example to secrets.env and fill in your credentials
CRAFTNOTE_URL=https://europe-west1-craftnote-live.cloudfunctions.net
CRAFTNOTE_API_KEY=your-api-key
CRAFTNOTE_EMAIL=your-email@example.com
CRAFTNOTE_PASSWORD=your-password

# Storage
DOWNLOAD_DIR=./downloads
```

## CLI Usage

```bash
# List all wind farms and turbines
uv run craftnote-scraper list-farms

# Download files for a specific wind farm
uv run craftnote-scraper download --farm "Boddin"

# Download files for all wind farms
uv run craftnote-scraper download --all

# Sync (incremental download, skip existing)
uv run craftnote-scraper sync

# Show download status
uv run craftnote-scraper status
```

## Key Implementation Details

### API Client

Uses `httpx.AsyncClient` for all HTTP requests:

```python
async with httpx.AsyncClient() as client:
    response = await client.get(
        f"{base_url}/api/v1/projects",
        headers={"X-CN-API-KEY": api_key}
    )
```

### Playwright Session

Persistent browser context to maintain login state:

```python
async with async_playwright() as p:
    browser = await p.chromium.launch_persistent_context(
        user_data_dir="./playwright-data",
        headless=True
    )
```

### File Detection in Chat

Target files by extension:
- `.pdf` - Service reports
- `.xlsx` / `.xls` - Spreadsheets

### Incremental Downloads

Track downloads in SQLite database to avoid re-downloading:
- Store file checksums
- Skip files already downloaded
- Allow force re-download option

## Development

```bash
# Setup
uv sync

# Run tests
uv run pytest

# Lint & format
uvx ruff format .
uvx ruff check --fix .

# Type check
uvx ty check .
```

## Verification Loop

Before committing, run:

```bash
uvx ruff format .
uvx ruff check --fix .
uvx ty check .
uv run pytest
```

## Limitations & Considerations

1. **Rate Limiting**: Add delays between requests to avoid being blocked
2. **Session Expiry**: Handle re-authentication when session expires
3. **Dynamic Content**: Chat may use infinite scroll - handle pagination
4. **File Naming**: Craftnote may not preserve original filenames
5. **Concurrent Downloads**: Limit parallelism to be respectful to the server

## License

Proprietary - Internal use only.
