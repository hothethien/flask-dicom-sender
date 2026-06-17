# DICOM Sender

A Flask application that sends DICOM files to a PACS server using `storescu` (dcm4che toolkit) and logs every file to a CSV.

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
| `DEFAULT_AE_TITLE` | `DCMRCV` | Called AE title |
| `DEFAULT_HOST` | `localhost` | Destination host |
| `DEFAULT_PORT` | `11112` | Destination port |
| `CONNECT_TIMEOUT` | `5000` | TCP connect timeout (ms) |
| `RESPONSE_TIMEOUT` | `30000` | DIMSE response timeout (ms) |
| `BATCH_SIZE` | `100` | Number of files per storescu call |

## How It Works

1. `POST /send-directory` returns immediately with a `job_id` (HTTP 202)
2. A background thread sends files in batches (default 100 files per `storescu` call)
3. Each batch uses a single JVM process and a single DICOM association for speed
4. Every file is logged to the CSV with timestamp, path, and status
5. Progress can be tracked via `GET /jobs/<job_id>`

## API Endpoints

### POST /send

Upload and send a single DICOM file (synchronous).

```bash
curl -X POST http://localhost:5000/send \
  -F "file=@/path/to/image.dcm"
```

### POST /send-directory

Start an async job to send all DICOM files from a directory. All parameters are optional if ENV vars are configured.

```bash
curl -X POST http://localhost:5000/send-directory \
  -H "Content-Type: application/json" \
  -d '{}'
```

Override directory or destination:

```bash
curl -X POST http://localhost:5000/send-directory \
  -H "Content-Type: application/json" \
  -d '{"directory": "/data/other-dicom", "ae_title": "OTHERPACS", "host": "10.0.0.5", "port": "4242"}'
```

Response:

```json
{"job_id": "abc-123-...", "status": "queued"}
```

### GET /jobs/<job_id>

Check progress of a send job.

```bash
curl http://localhost:5000/jobs/<job_id>
```

Response:

```json
{
  "job_id": "abc-123-...",
  "status": "running",
  "directory": "/data/dicom",
  "total": 50000,
  "sent": 12400,
  "success": 12300,
  "failure": 100,
  "started_at": "2026-06-17T02:50:00",
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

```
timestamp,file_path,status
2026-06-17T02:49:19.176288,/data/dicom/154C4745.dcm,success
2026-06-17T02:49:19.178040,/data/dicom/154C4B07.dcm,failure
```

## Docker Compose Example

```yaml
services:
  dicom-sender:
    build: .
    ports:
      - "5000:5000"
    environment:
      - UPLOAD_FOLDER=/data/dicom
      - DEFAULT_AE_TITLE=DCMRCV
      - DEFAULT_HOST=127.0.0.1
      - DEFAULT_PORT=11112
      - BATCH_SIZE=100
    volumes:
      - ./logs:/app/logs
      - /path/to/dicom/files:/data/dicom
    restart: unless-stopped
```
