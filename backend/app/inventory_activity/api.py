from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from .common import ActivityError, defaults, dumps
from .export_results import export_results
from .pipeline import analyze_workbook, explain

router = APIRouter(prefix="/api/activity", tags=["inventory-activity"])
DATA_ROOT = Path(os.environ.get("ACTIVITY_DATA_DIR", Path(__file__).resolve().parents[2] / "data/activity"))
EXPORTS = {"json": ("result.json", "application/json"), "csv": ("activity_assessments.csv", "text/csv"),
           "ttl": ("inventory-activity.ttl", "text/turtle"), "report": ("inventory-activity-mvp.md", "text/markdown")}


@contextmanager
def database():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA_ROOT / "jobs.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS activity_jobs (id TEXT PRIMARY KEY, metadata TEXT NOT NULL)")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_metadata(job_id: str, metadata: dict) -> None:
    with database() as conn:
        conn.execute("INSERT INTO activity_jobs (id, metadata) VALUES (?, ?)", (job_id, dumps(metadata)))


def metadata(job_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(404, "job not found")
    with database() as conn:
        row = conn.execute("SELECT metadata FROM activity_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "job not found")
    return json.loads(row["metadata"])


def completed_dir(job_id: str) -> Path:
    job = metadata(job_id)
    if job["status"] != "completed":
        raise HTTPException(409, job["error"])
    return DATA_ROOT / job_id


def read_json(directory: Path, name: str):
    return json.loads((directory / name).read_text(encoding="utf-8"))


@router.get("/config")
def get_config():
    return defaults()


@router.post("/jobs")
def create_job(file: UploadFile = File(...), observation_date: str | None = Form(None),
               threshold_days: int | None = Form(None, ge=0)):
    job_id = uuid4().hex
    directory = DATA_ROOT / job_id
    directory.mkdir(parents=True, exist_ok=False)
    info = {"job_id": job_id, "filename": Path(file.filename or "uploaded.xlsx").name,
            "created_at": datetime.now(timezone.utc).isoformat(), "data_quality": None, "error": None}
    try:
        content = file.file.read()
        (directory / "source.xlsx").write_bytes(content)
        config = defaults()
        policy = config["policy"]
        settings = {}
        if observation_date:
            settings = {"observation_date": observation_date,
                        "frequency_window_end": min(config["frequency_window_end"], observation_date)}
        if threshold_days is not None:
            if threshold_days != policy["threshold_value"]:
                policy["policy_id"] = f"slow-moving-custom-{threshold_days}d"
            policy["threshold_value"] = threshold_days
        result = analyze_workbook(content, info["filename"], settings, policy)
        export_results(result, directory)
        info.update(status="completed", data_quality=result["overview"]["counts"])
    except ActivityError as exc:
        info.update(status="failed", error={"message": str(exc), "details": []})
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Inventory activity job %s failed", job_id)
        info.update(status="failed", error={"message": "处理失败，请检查服务器日志", "details": [type(exc).__name__]})
    finally:
        file.file.close()
    save_metadata(job_id, info)
    return {"job_id": job_id, "status": info["status"]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    return metadata(job_id)


@router.get("/jobs/{job_id}/overview")
def get_overview(job_id: str):
    return read_json(completed_dir(job_id), "overview.json")


@router.get("/jobs/{job_id}/assessments")
def get_assessments(job_id: str, q: str = "", inactive_only: bool = False,
                    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    rows = read_json(completed_dir(job_id), "activity_assessments.json")
    needle = q.strip().casefold()
    filtered = [a for a in rows if (not inactive_only or a["inactive_candidate"] is True) and
                (not needle or needle in (a["material_code"] + " " + a["material_name"]).casefold())]
    return {"total": len(filtered), "items": filtered[offset:offset + limit]}


@router.get("/jobs/{job_id}/materials/{code:path}/explanation")
def get_explanation(job_id: str, code: str):
    result = read_json(completed_dir(job_id), "result.json")
    try:
        return explain(result, code)
    except KeyError:
        raise HTTPException(404, "material not observed in this input")


@router.get("/jobs/{job_id}/download/{format}")
def download(job_id: str, format: str):
    if format not in EXPORTS:
        raise HTTPException(404, "unsupported format")
    directory = completed_dir(job_id)
    name, content_type = EXPORTS[format]
    return FileResponse(directory / name, media_type=content_type, filename=name)
