# MinIO Production Deployment Guide

## Production Environment

- **Host**: WindeeProd (10.25.10.104)
- **MinIO API Port**: 9000
- **MinIO Console Port**: 9001
- **Docker Network**: host (exposed on host machine)
- **Access Method**: Direct HTTP (no SSL)

## Configuration

### Environment Variables

Add these to your `secrets.env`:

```bash
# MinIO Storage (Production)
MINIO_ENDPOINT=10.25.10.104:9000
MINIO_ACCESS_KEY=windee
MINIO_SECRET_KEY=windee-minio-secret-key-32chars!
MINIO_USE_SSL=false
MINIO_BUCKET=service-reports
```

### Important Notes

- **MINIO_ENDPOINT**: Must be `10.25.10.104:9000` (port 9000 is the S3 API, 9001 is the console)
- **MINIO_USE_SSL**: Set to `false` (MinIO is running on plain HTTP on the internal network)
- **MINIO_ACCESS_KEY**: Use `windee` (or the configured access key)
- **MINIO_SECRET_KEY**: Use the provided secret key with 32 characters

## Testing Connectivity

### 1. Test Network Access

```bash
# Should connect successfully
curl http://10.25.10.104:9001
# Response: HTML of MinIO Console (returns 200 OK)

# Test S3 API
curl http://10.25.10.104:9000
# Response: XML error (expected - no auth header)
```

### 2. Test Python Connection

```bash
cd /Users/anwender/DEV/craftnote_scraper
uv run python << 'EOF'
from craftnote_scraper.storage.minio_adapter import MinIOAdapter

adapter = MinIOAdapter(
    endpoint="10.25.10.104:9000",
    access_key="windee",
    secret_key="windee-minio-secret-key-32chars!",
    secure=False
)
print("✓ MinIO connection successful!")
EOF
```

### 3. Test with CLI (Dry Run)

```bash
# Dry run without upload
uv run craftnote-scraper sync --dry-run

# Dry run with MinIO upload
uv run craftnote-scraper sync --upload-to-minio --dry-run
```

## Production Deployment

### Step 1: Configure Credentials

Update or create `secrets.env` with production credentials:

```bash
cat >> secrets.env << 'EOF'

# MinIO Storage (Production)
MINIO_ENDPOINT=10.25.10.104:9000
MINIO_ACCESS_KEY=windee
MINIO_SECRET_KEY=windee-minio-secret-key-32chars!
MINIO_USE_SSL=false
MINIO_BUCKET=service-reports
EOF
```

### Step 2: Verify Configuration

```bash
# Test dry-run sync with MinIO upload
uv run craftnote-scraper sync --upload-to-minio --dry-run

# Should not download any files (already synced)
# But should test MinIO connectivity
```

### Step 3: Enable in Daemon

Update the launchd plist to enable MinIO uploads:

```bash
# Path: ~/Library/LaunchAgents/de.windreserve.craftnote-sync.plist
```

Add environment variables to the plist:

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>MINIO_ENDPOINT</key>
    <string>10.25.10.104:9000</string>
    <key>MINIO_ACCESS_KEY</key>
    <string>windee</string>
    <key>MINIO_SECRET_KEY</key>
    <string>windee-minio-secret-key-32chars!</string>
    <key>MINIO_USE_SSL</key>
    <string>false</string>
    <key>SYNC_SCHEDULE</key>
    <string>0 20 * * *</string>
</dict>
```

### Step 4: Restart Daemon

```bash
# Unload old daemon
launchctl unload ~/Library/LaunchAgents/de.windreserve.craftnote-sync.plist

# Load new daemon with updated config
launchctl load ~/Library/LaunchAgents/de.windreserve.craftnote-sync.plist

# Verify it's running
launchctl list | grep craftnote
```

### Step 5: Monitor

```bash
# Watch logs
tail -f ~/DEV/craftnote_scraper/logs/daemon.error.log

# Look for MinIO upload messages
grep -i "minio\|upload" ~/DEV/craftnote_scraper/logs/daemon.error.log
```

## Bucket Structure

Files are organized in MinIO with the following structure:

```
service-reports/
├── inbox/
│   ├── wind-farm-name/
│   │   ├── turbine-name/
│   │   │   ├── 2026-04-21_report-filename.pdf
│   │   │   ├── 2026-04-21_report-filename.pdf.meta.json
│   │   │   └── ...
│   │   └── ...
│   └── ...
└── archive/
    └── ...
```

### Metadata Sidecars

Each uploaded file has a `.meta.json` sidecar with:

```json
{
  "source": "craftnote",
  "craftnote_project_id": "uuid",
  "original_filename": "Report_20260421.pdf",
  "wind_farm": "Boddin",
  "turbine_name": "HJW BO 3",
  "checksum_sha256": "sha256-hash",
  "uploaded_at": "2026-04-21T15:30:45Z",
  "uploaded_by": "craftnote_scraper",
  "file_size_bytes": 12345,
  "content_type": "application/pdf"
}
```

## Troubleshooting

### Connection Timeout

```
Error: Could not connect to 10.25.10.104:9000
```

**Solutions:**
- Verify network connectivity: `ping 10.25.10.104`
- Check MinIO container is running: `ssh windee@10.25.10.104 docker ps | grep minio`
- Check firewall rules allow port 9000

### Authentication Failed

```
Error: Invalid access key / secret key
```

**Solutions:**
- Verify credentials in `secrets.env`
- Check environment variables are loaded: `echo $MINIO_ACCESS_KEY`
- Confirm credentials match production setup

### SSL Certificate Error

```
Error: SSL verification failed
```

**Solutions:**
- Verify `MINIO_USE_SSL=false` (MinIO is HTTP-only on internal network)
- Don't use HTTPS with this endpoint

### Bucket Permission Denied

```
Error: Access Denied
```

**Solutions:**
- Verify bucket `service-reports` exists
- Check user permissions on the bucket
- Contact MinIO admin to verify access

## Monitoring

### Check MinIO Console

```bash
# Open in browser
open http://10.25.10.104:9001

# Login with:
# Username: windee
# Password: windee-minio-secret-key-32chars!
```

### Query Upload Status

```bash
sqlite3 downloads.db << 'EOF'
SELECT 
    wind_farm, 
    turbine, 
    COUNT(*) as files,
    COUNT(CASE WHEN minio_uploaded_at IS NOT NULL THEN 1 END) as uploaded,
    COUNT(CASE WHEN minio_uploaded_at IS NULL THEN 1 END) as pending
FROM downloaded_files
GROUP BY wind_farm, turbine
ORDER BY uploaded DESC;
EOF
```

### Recent Uploads

```bash
sqlite3 downloads.db << 'EOF'
SELECT 
    wind_farm, 
    turbine, 
    filename, 
    minio_uploaded_at
FROM downloaded_files
WHERE minio_uploaded_at IS NOT NULL
ORDER BY minio_uploaded_at DESC
LIMIT 20;
EOF
```

## Rollback

If issues occur, you can disable MinIO uploads without redeploying:

```bash
# Edit secrets.env and remove MinIO variables, or set MINIO_ACCESS_KEY to empty
# Then restart daemon

launchctl unload ~/Library/LaunchAgents/de.windreserve.craftnote-sync.plist
launchctl load ~/Library/LaunchAgents/de.windreserve.craftnote-sync.plist
```

The scraper will continue to work without MinIO upload. Files will still be downloaded locally.

## Asynchronous Upload Workflow (Recommended)

Since MinIO uploads add significant overhead to the sync process (checksum validation, cache loading), it's recommended to decouple downloads from uploads:

### Architecture

- **Daily Sync** (fast): Download new files only, skip MinIO uploads
- **Separate Upload Job** (scheduled daily): Upload all pending files to MinIO

### Setup

#### 1. Modify Daemon Configuration

Update the launchd plist to remove `--upload-to-minio`:

```xml
<key>ProgramArguments</key>
<array>
    <string>/path/to/craftnote-scraper</string>
    <string>daemon</string>
    <!-- Remove: <string>--upload-to-minio</string> -->
</array>
```

This makes sync runs complete in ~5 minutes instead of 30+ minutes.

#### 2. Create Daily Upload Cron Job

Add this to your crontab (`crontab -e`):

```bash
# Run upload-pending daily at 2 AM (off-peak hours)
0 2 * * * cd /Users/anwender/DEV/craftnote_scraper && \
  export MINIO_ENDPOINT=10.25.10.104:9000 && \
  export MINIO_ACCESS_KEY=windee && \
  export MINIO_SECRET_KEY='windee-minio-secret-key-32chars!' && \
  export MINIO_USE_SSL=false && \
  export MINIO_BUCKET=service-reports && \
  uv run craftnote-scraper upload-pending >> ~/craftnote-upload.log 2>&1
```

#### 3. Verify Uploads

Check the upload log:

```bash
tail -f ~/craftnote-upload.log
```

### Advantages

- **Fast Syncs**: Downloads complete in ~5 minutes (no MinIO overhead)
- **Resilient**: Failed uploads don't block downloads
- **Flexible Scheduling**: Upload during off-peak hours
- **Monitoring**: Separate logs for upload activity
- **Easy Troubleshooting**: Can manually run `upload-pending` for debugging

### Manual Upload

To manually upload pending files:

```bash
export MINIO_ENDPOINT=10.25.10.104:9000
export MINIO_ACCESS_KEY=windee
export MINIO_SECRET_KEY='windee-minio-secret-key-32chars!'
export MINIO_USE_SSL=false
export MINIO_BUCKET=service-reports

# Upload all pending files
uv run craftnote-scraper upload-pending --verbose

# Check pending count
sqlite3 downloads.db "SELECT COUNT(*) as pending FROM downloaded_files WHERE minio_uploaded_at IS NULL;"
```

## Next Steps

1. ✓ Test connectivity to MinIO
2. ✓ Verify credentials work
3. Monitor first production sync with uploads
4. Verify files appear in MinIO bucket
5. Set up automated health checks (future enhancement)
