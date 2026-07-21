# DICOM Sender

A high-performance, resilient Flask application that sends DICOM files to a PACS server using `storescu` (`dcm4che` toolkit), featuring batch execution, single-file error fallback, thread-safe CSV logging, and progress tracking.

## Prerequisites

- Python 3.9+
- `storescu` from dcm4che toolkit (included in Docker image)

## Setup

```bash
cd dicom-sender
pip install -r requirements.txt
python app.py
```

Or with Docker:

```bash
docker compose up -d
```

## Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `UPLOAD_FOLDER` | `/tmp/dicom-uploads` | Default directory to send DICOM files from |
| `CSV_LOG_FILE` | `dicom_send_log.csv` | Path to the CSV log file |
| `STORESCU_PATH` | `storescu` | Path to the storescu binary |
| `DEFAULT_AE_TITLE` | `DCMRCV` | Called AE title (PACS Server) |
| `DEFAULT_HOST` | `localhost` | Destination host |
| `DEFAULT_PORT` | `11112` | Destination port |
| `CONNECT_TIMEOUT` | `5000` | TCP connect timeout (ms) |
| `RESPONSE_TIMEOUT` | `30000` | DIMSE response timeout (ms) |
| `BATCH_SIZE` | `100` | Number of files per storescu call |
| `MAX_RETRIES` | `2` | Maximum retry attempts per batch before fallback |

## How It Works

1. **Async Directory Processing**: `POST /send-directory` returns immediately with a `job_id` (HTTP 202).
2. **Batching**: A background thread sends files in batches (default 100 files per `storescu` call) to maintain high throughput and minimize JVM startup overhead and TCP association renegotiations.
3. **Batch Retry & Single-File Fallback**:
   - If a batch fails, it retries up to `MAX_RETRIES` times (with 1s backoff).
   - If the batch still fails (e.g. due to a corrupted DICOM file in the batch), the worker automatically enters **Single-file Fallback mode**: it sends each file in the batch individually to isolate invalid files, ensuring all valid files are successfully transmitted to PACS.
4. **Thread-Safe Batch CSV Logging**: Log entries are written in bulk with file size in MB (`file_size_mb`) under a thread lock (`threading.Lock()`), ensuring low Disk I/O overhead and zero race conditions.
5. **Progress Tracking**: Track job progress real-time via `GET /jobs/<job_id>`.

## API Endpoints

### POST /send

Upload and send a single DICOM file (synchronous).

```bash
curl -X POST http://localhost:5001/send \
  -F "file=@/path/to/image.dcm"
```

### POST /send-directory

Start an async job to send all DICOM files from a directory. All parameters are optional if ENV vars are configured.

```bash
curl -X POST http://localhost:5001/send-directory \
  -H "Content-Type: application/json" \
  -d '{}'
```

Override directory or destination:

```bash
curl -X POST http://localhost:5001/send-directory \
  -H "Content-Type: application/json" \
  -d '{"directory": "/dicoms/other", "ae_title": "DCMSRV", "host": "10.0.0.5", "port": "11112"}'
```

Response:

```json
{"job_id": "abc-123-...", "status": "queued"}
```

### GET /jobs/<job_id>

Check progress of a send job.

```bash
curl http://localhost:5001/jobs/<job_id>
```

Response:

```json
{
  "job_id": "abc-123-...",
  "status": "running",
  "directory": "/dicoms",
  "total": 50000,
  "sent": 12400,
  "success": 12399,
  "failure": 1,
  "started_at": "2026-07-21T10:00:00",
  "finished_at": null
}
```

### GET /jobs

List all jobs.

### GET /logs

Return all CSV log entries as JSON.

### GET /health

Health check.

## CSV Log Format

CSV logs are automatically initialized with headers and written thread-safely:

```csv
timestamp,file_path,file_size_mb,status
2026-07-21T10:28:45.123456,/dicoms/154C4745.dcm,5.25,success
2026-07-21T10:28:46.654321,/dicoms/154C4B07.dcm,0.48,failure
```

## Docker Compose Example

```yaml
services:
  dicom-sender:
    container_name: dicom-sender
    image: registry.labspace.io.vn/dicom-sender:2.1
    ports:
      - "5001:5001"
    environment:
      - TZ=Asia/Ho_Chi_Minh
      - DEFAULT_AE_TITLE=DCMSRV
      - DEFAULT_HOST=X.X.X.X
      - DEFAULT_PORT=11112
      - CONNECT_TIMEOUT=5000
      - RESPONSE_TIMEOUT=30000
      - UPLOAD_FOLDER=/dicoms
      - BATCH_SIZE=100
      - MAX_RETRIES=2
    volumes:
      - ./logs:/app/logs
      - ./dicoms:/dicoms
    restart: unless-stopped
```
