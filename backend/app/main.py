from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .analysis import analyze
from .database import connect, get_job, save_job
from .excel_parser import parse_workbook
from .models import DataQualityError


app = FastAPI(title="库存健康度 Demo API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...)) -> dict[str, str]:
    job_id = uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    content = await file.read()

    with connect() as conn:
        try:
            transactions, data_quality = parse_workbook(content)
            overview, details = analyze(transactions, data_quality)
            save_job(
                conn,
                job_id=job_id,
                filename=file.filename or "uploaded.xlsx",
                status="completed",
                created_at=created_at,
                data_quality=data_quality,
                overview=overview,
                details=details,
            )
            return {"job_id": job_id, "status": "completed"}
        except DataQualityError as exc:
            error = {"error_type": "DATA_QUALITY_FAILED", "message": exc.message, "details": exc.details}
            save_job(
                conn,
                job_id=job_id,
                filename=file.filename or "uploaded.xlsx",
                status="failed",
                created_at=created_at,
                error=error,
            )
            return {"job_id": job_id, "status": "failed"}
        except Exception as exc:
            error = {"error_type": "INTERNAL_ERROR", "message": "系统繁忙，请稍后再试", "details": [str(exc)]}
            save_job(
                conn,
                job_id=job_id,
                filename=file.filename or "uploaded.xlsx",
                status="failed",
                created_at=created_at,
                error=error,
            )
            return {"job_id": job_id, "status": "failed"}


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str) -> dict:
    with connect() as conn:
        job = get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "job_id": job["id"],
        "filename": job["filename"],
        "status": job["status"],
        "created_at": job["created_at"],
        "data_quality": job["data_quality"],
        "error": job["error"],
    }


@app.get("/api/jobs/{job_id}/overview")
def read_overview(job_id: str) -> dict:
    job = _completed_job(job_id)
    return job["overview"]


@app.get("/api/jobs/{job_id}/details/{indicator_id}")
def read_detail(job_id: str, indicator_id: str) -> dict:
    job = _completed_job(job_id)
    details = job["details"] or {}
    if indicator_id not in details:
        raise HTTPException(status_code=404, detail="indicator not found")
    return details[indicator_id]


def _completed_job(job_id: str) -> dict:
    with connect() as conn:
        job = get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail=job["error"] or "job failed")
    return job
