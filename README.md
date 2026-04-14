# Craftnote Scraper

Automated tool to download service report PDFs and spreadsheets (XLSX) from Craftnote project chats for wind turbine maintenance documentation.

## Features

- **API-based project discovery** - Enumerate all projects and build wind farm/turbine structure
- **Browser automation** - Download files from project chats using Playwright
- **Incremental sync** - Only process projects modified since last sync
- **Scheduled sync** - Run as a daemon with cron-style scheduling (AIOClock)
- **MinIO integration** - Upload files to S3-compatible storage
- **Download tracking** - SQLite database tracks all downloads and sync status
- **Matrix room mapping** - Link Craftnote projects to Matrix room IDs

## Quick Start

```bash
# Install dependencies
uv sync

# List all wind farms
uv run craftnote-scraper list-farms

# Download files for a specific wind farm
uv run craftnote-scraper download --farm "Boddin"

# Incremental sync (projects modified in last 24 hours)
uv run craftnote-scraper sync-incremental --since 24h

# Run as daemon (daily sync at 8 PM)
uv run craftnote-scraper daemon
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Data Flow                                       │
│                                                                              │
│  ┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌───────────┐ │
│  │ Craftnote   │     │ Playwright  │     │ Local        │     │ MinIO     │ │
│  │ API         │────▶│ Browser     │────▶│ Storage      │────▶│ S3        │ │
│  │ (metadata)  │     │ (files)     │     │ + SQLite     │     │ (backup)  │ │
│  └─────────────┘     └─────────────┘     └──────────────┘     └───────────┘ │
│        │                   │                    │                           │
│        ▼                   ▼                    ▼                           │
│  - List projects     - Login to web       - downloads/                      │
│  - Filter modified   - Navigate chat      - downloads.db                    │
│  - Get metadata      - Download files     - Track checksums                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
craftnote_scraper/
├── src/craftnote_scraper/
│   ├── api/                    # Craftnote API client
│   │   ├── client.py           # Async HTTP client with retry
│   │   ├── models.py           # Pydantic models (Project, ProjectFile)
│   │   └── exceptions.py       # API error hierarchy
│   ├── scraper/                # Playwright browser automation
│   │   ├── browser.py          # Browser context management
│   │   ├── login.py            # Authentication flow
│   │   ├── downloader.py       # File download from chat
│   │   └── exceptions.py       # Scraper errors
│   ├── mapping/                # Wind farm/turbine mapping
│   │   ├── models.py           # WindFarm, WindTurbine dataclasses
│   │   └── wind_farms.py       # Structure discovery and mapping
│   ├── storage/                # File storage and tracking
│   │   ├── tracker.py          # SQLite download/sync tracking
│   │   ├── models.py           # DownloadedFile, FileType
│   │   ├── organizer.py        # File path utilities, checksums
│   │   └── minio_adapter.py    # MinIO S3 upload
│   ├── config.py               # Shared constants and configuration
│   ├── scheduler.py            # AIOClock daemon for scheduled sync
│   ├── retry.py                # Exponential backoff retry logic
│   └── cli.py                  # Typer CLI entry point
├── tests/                      # pytest test suite
├── logs/                       # Daemon logs
├── downloads/                  # Downloaded files
├── downloads.db                # SQLite tracking database
├── secrets.env                 # Credentials (not in git)
└── pyproject.toml              # Project configuration
```

## CLI Commands

### List Wind Farms

```bash
uv run craftnote-scraper list-farms
uv run craftnote-scraper list-turbines --farm "Boddin"
```

### Download Files

```bash
# Download all files for a wind farm
uv run craftnote-scraper download --farm "Boddin"

# Download from all wind farms
uv run craftnote-scraper download --all

# Resume interrupted download (skip existing folders)
uv run craftnote-scraper download --all --resume

# Dry run (show what would be downloaded)
uv run craftnote-scraper download --all --dry-run
```

### Incremental Sync

```bash
# Sync projects modified in last 24 hours
uv run craftnote-scraper sync-incremental --since 24h

# Sync projects modified in last 7 days
uv run craftnote-scraper sync-incremental --since 7d

# Sync projects modified since last sync run
uv run craftnote-scraper sync-incremental --since-last-run

# Sync with MinIO upload
uv run craftnote-scraper sync-incremental --since 24h --upload-to-minio

# Dry run
uv run craftnote-scraper sync-incremental --since 24h --dry-run
```

### Daemon Mode

```bash
# Run with default schedule (daily at 8 PM Europe/Berlin)
uv run craftnote-scraper daemon

# Custom schedule (cron format)
uv run craftnote-scraper daemon --schedule "0 6 * * *"

# With MinIO upload
uv run craftnote-scraper daemon --upload-to-minio
```

### Status and Mapping

```bash
# Show download statistics
uv run craftnote-scraper status

# Show Craftnote to Matrix mapping
uv run craftnote-scraper mapping
```

## Configuration

### Environment Variables

Create `secrets.env` in the project root:

```bash
# Craftnote API
CRAFTNOTE_URL=https://europe-west1-craftnote-live.cloudfunctions.net
CRAFTNOTE_API_KEY=your-api-key
CRAFTNOTE_EMAIL=your-email@example.com
CRAFTNOTE_PASSWORD=your-password

# MinIO Storage (optional)
MINIO_ENDPOINT=10.10.10.55:9000
MINIO_ACCESS_KEY=your-access-key
MINIO_SECRET_KEY=your-secret-key
MINIO_USE_SSL=false
MINIO_BUCKET=service-reports

# Scheduler (optional)
SYNC_SCHEDULE=0 20 * * *
SYNC_LOOKBACK_HOURS=24
```

### Excluded Folders

The following folders are excluded from sync (not wind farm service reports):

- Administrative: DFÜ, IT Projekte, Lager, Marketing, Test, etc.
- Real Estate: Immobilien, Eimsbüttler Chaussee, etc.
- Insurance: Versicherungsfälle, Gewährleistung, etc.
- External: Fremdaufträge, Fuhrpark, etc.

See `src/craftnote_scraper/config.py` for the full list.

## Production Deployment (macOS)

The daemon can be run as a launchd service:

```bash
# Service location
~/Library/LaunchAgents/de.windreserve.craftnote-sync.plist

# Start service
launchctl load ~/Library/LaunchAgents/de.windreserve.craftnote-sync.plist

# Stop service
launchctl unload ~/Library/LaunchAgents/de.windreserve.craftnote-sync.plist

# Check status
launchctl list | grep craftnote

# View logs
tail -f ~/DEV/craftnote_scraper/logs/daemon.log
```

## Database Schema

### downloaded_files

Tracks all downloaded files:

| Column | Type | Description |
|--------|------|-------------|
| file_id | TEXT | Primary key (project_id + filename) |
| filename | TEXT | Original filename |
| file_type | TEXT | pdf, xlsx, or xls |
| downloaded_at | TEXT | ISO timestamp |
| path | TEXT | Local file path |
| checksum | TEXT | SHA256 hash |
| wind_farm | TEXT | Wind farm name |
| turbine | TEXT | Turbine name |
| minio_object_key | TEXT | MinIO object key (if uploaded) |
| minio_uploaded_at | TEXT | Upload timestamp |

### project_sync_status

Tracks per-project sync status:

| Column | Type | Description |
|--------|------|-------------|
| project_id | TEXT | Primary key |
| project_name | TEXT | Project name |
| wind_farm | TEXT | Wind farm name |
| last_synced_at | TEXT | ISO timestamp |
| last_edited_at | TEXT | Last edit time from API |
| files_downloaded | INTEGER | Files downloaded in sync |
| sync_status | TEXT | success, failed, or partial |

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

### Verification Loop

Before committing:

```bash
uvx ruff format .
uvx ruff check --fix .
uvx ty check .
uv run pytest
```

## API Details

### Incremental Sync Logic

1. Fetch all projects from Craftnote API (~15 seconds for 1500+ projects)
2. Filter to projects with `last_edited_date > cutoff_time`
3. Exclude administrative folders (not wind farms)
4. For each modified project:
   - Navigate to project chat with Playwright
   - Find and download PDF/XLSX/XLS files
   - Track downloads in SQLite
   - Upload to MinIO (if enabled)
   - Record sync status

### Estimated Time Savings

| Approach | Projects | Est. Time |
|----------|----------|-----------|
| Full sync (all projects) | ~1500 | ~4+ hours |
| Incremental (24h) | ~20 | ~5 minutes |

**~98% reduction in processing time**

## License

Proprietary - Internal use only.
