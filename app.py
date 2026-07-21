import csv
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/tmp/dicom-uploads")
CSV_LOG_FILE = os.environ.get("CSV_LOG_FILE", "dicom_send_log.csv")
STORESCU_PATH = os.environ.get("STORESCU_PATH", "storescu")

# Default destination
DEFAULT_AE_TITLE = os.environ.get("DEFAULT_AE_TITLE", "DCMRCV")
DEFAULT_HOST = os.environ.get("DEFAULT_HOST", "localhost")
DEFAULT_PORT = os.environ.get("DEFAULT_PORT", "11112")

# Timeouts in ms
CONNECT_TIMEOUT = os.environ.get("CONNECT_TIMEOUT", "5000")
RESPONSE_TIMEOUT = os.environ.get("RESPONSE_TIMEOUT", "30000")

# How many files to send per storescu call (to avoid too-long command)
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "100"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "2"))

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

CSV_HEADERS = ["timestamp", "file_path", "file_size_mb", "status"]

# In-memory job tracker & thread lock
jobs = {}
csv_lock = threading.Lock()


def init_csv():
    """Ensure parent directory exists and initialize CSV with headers if file does not exist."""
    parent_dir = os.path.dirname(CSV_LOG_FILE)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    with csv_lock:
        if not os.path.exists(CSV_LOG_FILE):
            with open(CSV_LOG_FILE, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADERS)


def log_to_csv(records):
    """Log a single record dict or a list of record dicts to CSV safely (thread-safe)."""
    if isinstance(records, dict):
        records = [records]

    with csv_lock:
        with open(CSV_LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            for record in records:
                writer.writerow([record.get(h, "") for h in CSV_HEADERS])


# Automatically initialize CSV on module load
init_csv()


def send_dicom(file_path: str, ae_title: str, host: str, port: str) -> str:
    """Send a DICOM file/directory using storescu. Returns 'success' or 'failure'."""
    connection = f"{ae_title}@{host}:{port}"
    cmd = [
        STORESCU_PATH,
        "-c", connection,
        "--connect-timeout", CONNECT_TIMEOUT,
        "--response-timeout", RESPONSE_TIMEOUT,
        file_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return "success" if result.returncode == 0 else "failure"
    except Exception:
        return "failure"


def send_directory_task(job_id: str, directory: str, ae_title: str, host: str, port: str):
    """Background task: send files in batches and log each to CSV."""
    dicom_files = sorted([
        f for f in Path(directory).rglob("*")
        if f.is_file() and f.suffix.lower() in (".dcm", ".dicom", "")
    ])

    total = len(dicom_files)
    jobs[job_id]["total"] = total
    jobs[job_id]["status"] = "running"

    success_count = 0
    failure_count = 0

    # Send in batches with single-file fallback
    for i in range(0, total, BATCH_SIZE):
        batch = dicom_files[i:i + BATCH_SIZE]
        batch_paths = [str(f) for f in batch]

        # Build storescu command with multiple files
        connection = f"{ae_title}@{host}:{port}"
        cmd = [
            STORESCU_PATH,
            "-c", connection,
            "--connect-timeout", CONNECT_TIMEOUT,
            "--response-timeout", RESPONSE_TIMEOUT,
        ] + batch_paths

        # Try sending the full batch first (with retries if needed)
        batch_success = False
        for attempt in range(MAX_RETRIES):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if result.returncode == 0:
                    batch_success = True
                    break
            except Exception:
                pass
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)

        now_iso = datetime.now().isoformat()

        if batch_success:
            # All files in batch succeeded
            records = [
                {
                    "timestamp": now_iso,
                    "file_path": str(f),
                    "file_size_mb": round(f.stat().st_size / (1024 * 1024), 2) if f.exists() else 0.0,
                    "status": "success",
                }
                for f in batch
            ]
            log_to_csv(records)
            success_count += len(batch)
        else:
            # Fallback: Batch failed. Try sending files individually to isolate any corrupted/failed file.
            fallback_records = []
            for f in batch:
                file_status = send_dicom(str(f), ae_title, host, port)
                fallback_records.append({
                    "timestamp": datetime.now().isoformat(),
                    "file_path": str(f),
                    "file_size_mb": round(f.stat().st_size / (1024 * 1024), 2) if f.exists() else 0.0,
                    "status": file_status,
                })
                if file_status == "success":
                    success_count += 1
                else:
                    failure_count += 1
            log_to_csv(fallback_records)

        jobs[job_id]["sent"] = success_count + failure_count
        jobs[job_id]["success"] = success_count
        jobs[job_id]["failure"] = failure_count

    jobs[job_id]["status"] = "completed"
    jobs[job_id]["finished_at"] = datetime.now().isoformat()


@app.route("/send", methods=["POST"])
def send():
    """Send a single DICOM file (synchronous)."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    ae_title = request.form.get("ae_title", DEFAULT_AE_TITLE)
    host = request.form.get("host", DEFAULT_HOST)
    port = request.form.get("port", DEFAULT_PORT)

    filename = secure_filename(file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}_{filename}")
    file.save(file_path)

    try:
        bytes_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        file_size_mb = round(bytes_size / (1024 * 1024), 2)
        status = send_dicom(file_path, ae_title, host, port)
        record = {
            "timestamp": datetime.now().isoformat(),
            "file_path": file_path,
            "file_size_mb": file_size_mb,
            "status": status,
        }
        log_to_csv(record)
        return jsonify(record), 200 if status == "success" else 500
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.route("/send-directory", methods=["POST"])
def send_directory():
    """
    Start an async job to send all DICOM files from a directory.
    Returns immediately with a job_id to track progress.

    JSON body (all optional if ENV vars are set):
      - directory: defaults to UPLOAD_FOLDER
      - ae_title: defaults to DEFAULT_AE_TITLE
      - host: defaults to DEFAULT_HOST
      - port: defaults to DEFAULT_PORT
    """
    data = request.get_json() or {}

    directory = data.get("directory", UPLOAD_FOLDER)
    if not os.path.isdir(directory):
        return jsonify({"error": f"Directory not found: {directory}"}), 404

    ae_title = data.get("ae_title", DEFAULT_AE_TITLE)
    host = data.get("host", DEFAULT_HOST)
    port = data.get("port", DEFAULT_PORT)

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "directory": directory,
        "total": 0,
        "sent": 0,
        "success": 0,
        "failure": 0,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
    }

    thread = threading.Thread(
        target=send_directory_task,
        args=(job_id, directory, ae_title, host, port),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id, "status": "queued"}), 202


@app.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    """Check the status/progress of a send job."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(jobs[job_id])


@app.route("/jobs", methods=["GET"])
def list_jobs():
    """List all jobs."""
    return jsonify(list(jobs.values()))


@app.route("/logs", methods=["GET"])
def get_logs():
    """Return all log entries from the CSV file."""
    if not os.path.exists(CSV_LOG_FILE):
        return jsonify([])

    logs = []
    with csv_lock:
        with open(CSV_LOG_FILE, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                logs.append(row)
    return jsonify(logs)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
