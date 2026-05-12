"""
ASIQ — Production REST API
Jalankan di EC2: uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4
Docs tersedia di: http://<EC2_IP>:8000/docs
"""

import io
import json
import logging
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from fastapi import (
    Depends, FastAPI, File, Form, HTTPException, Security,
    UploadFile, status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

load_dotenv(override=True)


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("asiq.api")


# ── Config dari environment ───────────────────────────────────────────────────

API_KEY         = os.getenv("API_KEY", "")
S3_BUCKET       = os.getenv("S3_BUCKET", "")
AWS_REGION      = os.getenv("AWS_REGION", "ap-southeast-1")
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", 86400))   # default 24 jam
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")


# ── Redis (job store) ─────────────────────────────────────────────────────────

from db_connection import REDIS_ENABLED, redis_client


# ── S3 client ─────────────────────────────────────────────────────────────────

_s3: Optional[boto3.client] = None
if S3_BUCKET:
    try:
        _s3 = boto3.client("s3", region_name=AWS_REGION)
        log.info("S3 client siap. Bucket: %s", S3_BUCKET)
    except Exception as e:
        log.warning("S3 tidak dapat diinisialisasi: %s", e)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="ASIQ API",
    description=(
        "**Adaptive Student Inclusive Learning** — REST API untuk generate "
        "RPP Inklusif berbasis AI.\n\n"
        "Semua endpoint membutuhkan header `X-API-Key`."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── API Key auth ──────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(key: str = Security(_api_key_header)):
    if API_KEY and key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key tidak valid atau tidak disertakan.",
        )
    return key


# ── Job status constants ──────────────────────────────────────────────────────

class JobStatus:
    QUEUED     = "queued"
    PROCESSING = "processing"
    DONE       = "done"
    FAILED     = "failed"


# ── Job storage helpers (Redis dengan fallback ke memory) ─────────────────────

_memory_store: dict = {}


def _set_job(job_id: str, data: dict) -> None:
    if REDIS_ENABLED:
        redis_client.setex(
            f"job:{job_id}",
            JOB_TTL_SECONDS,
            json.dumps(data, ensure_ascii=False),
        )
    else:
        _memory_store[job_id] = data


def _get_job(job_id: str) -> Optional[dict]:
    if REDIS_ENABLED:
        raw = redis_client.get(f"job:{job_id}")
        return json.loads(raw) if raw else None
    return _memory_store.get(job_id)


def _update_job(job_id: str, patch: dict) -> None:
    existing = _get_job(job_id) or {}
    _set_job(job_id, {**existing, **patch})


# ── S3 helpers ────────────────────────────────────────────────────────────────

def _upload_to_s3(local_path: str, s3_key: str) -> Optional[str]:
    if not _s3 or not S3_BUCKET:
        return None
    try:
        _s3.upload_file(local_path, S3_BUCKET, s3_key)
        url = _s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": s3_key},
            ExpiresIn=JOB_TTL_SECONDS,
        )
        log.info("PDF terupload ke S3: %s", s3_key)
        return url
    except ClientError as e:
        log.error("Gagal upload ke S3: %s", e)
        return None


# ── Parse skor dari output insight agent ─────────────────────────────────────

def _parse_scores(insight_out: str) -> tuple[int, int]:
    readability = 0
    wcag = 0
    m = re.search(r"[Rr]eadability\s+[Ss]core.*?(\d{1,3})", insight_out)
    if m:
        readability = min(int(m.group(1)), 100)
    m = re.search(r"[Ss]kor\s+[Ii]nklusivitas.*?(\d{1,3})", insight_out)
    if m:
        wcag = min(int(m.group(1)), 100)
    return readability, wcag


# ── Simpan job ke PostgreSQL ──────────────────────────────────────────────────

def _save_to_postgres(job_id: str, data: dict, readability: int, wcag: int, pdf_url: Optional[str]) -> None:
    try:
        from db_connection import get_postgres_connection
        conn   = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rpp_jobs (
                job_id         TEXT PRIMARY KEY,
                nama_siswa     TEXT,
                kelas          TEXT,
                mata_pelajaran TEXT,
                readability    INT,
                wcag_score     INT,
                pdf_url        TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            """
            INSERT INTO rpp_jobs (job_id, nama_siswa, kelas, mata_pelajaran, readability, wcag_score, pdf_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_id) DO NOTHING
            """,
            (job_id, data["nama_siswa"], data["kelas"],
             data["mata_pelajaran"], readability, wcag, pdf_url),
        )
        conn.commit()
        cursor.close()
        conn.close()
        log.info("Job %s tersimpan ke PostgreSQL.", job_id)
    except Exception as e:
        log.warning("PostgreSQL tidak tersedia, skip simpan history: %s", e)


# ── Background pipeline ───────────────────────────────────────────────────────

def _run_pipeline(job_id: str, data: dict, doc_bytes: Optional[bytes], doc_ext: Optional[str]) -> None:
    try:
        from main import _create_output_dir, _load_document, _save_markdown_files, generate_pdf
        from crew import AsiqAgents

        # Step 1 — load dokumen jika ada
        _update_job(job_id, {"status": JobStatus.PROCESSING, "step": "Membaca dokumen materi..."})
        if doc_bytes and doc_ext:
            with tempfile.NamedTemporaryFile(suffix=doc_ext, delete=False) as tmp:
                tmp.write(doc_bytes)
                tmp_path = tmp.name
            try:
                data["materi_mentah"] = _load_document(tmp_path)
                log.info("Job %s: dokumen dimuat (%d karakter)", job_id, len(data["materi_mentah"]))
            finally:
                os.unlink(tmp_path)

        if not data.get("materi_mentah"):
            raise ValueError("Materi pembelajaran tidak boleh kosong.")

        # Step 2 — jalankan crew AI
        _update_job(job_id, {"step": "Agent 1: Profiling siswa..."})
        profil = (
            f"Nama: {data['nama_siswa']} | Kelas: {data['kelas']} | "
            f"Mata Pelajaran: {data['mata_pelajaran']} | Kondisi/Gejala: {data['gejala']}"
        )

        hasil = AsiqAgents().crew().kickoff(inputs={
            "profil_siswa":  profil,
            "materi_mentah": data["materi_mentah"],
        })

        _update_job(job_id, {"step": "Agent 3: Audit inklusivitas..."})

        try:
            profiling_out = hasil.tasks_output[0].raw
            adaptive_out  = hasil.tasks_output[1].raw
            insight_out   = hasil.tasks_output[2].raw
        except (AttributeError, IndexError):
            profiling_out = str(hasil)
            adaptive_out  = ""
            insight_out   = ""

        # Step 3 — generate PDF
        _update_job(job_id, {"step": "Membuat PDF RPP Inklusif..."})
        output_dir = _create_output_dir(data["nama_siswa"])
        _save_markdown_files(output_dir, profiling_out, adaptive_out, insight_out)
        pdf_path = generate_pdf(data, profiling_out, adaptive_out, insight_out, output_dir)
        log.info("Job %s: PDF dibuat di %s", job_id, pdf_path)

        # Step 4 — upload ke S3
        pdf_url = None
        if S3_BUCKET:
            _update_job(job_id, {"step": "Mengupload PDF ke S3..."})
            s3_key  = f"rpp/{job_id}/{os.path.basename(pdf_path)}"
            pdf_url = _upload_to_s3(pdf_path, s3_key)

        # Step 5 — parse skor
        readability, wcag = _parse_scores(insight_out)

        # Step 6 — simpan ke PostgreSQL
        _save_to_postgres(job_id, data, readability, wcag, pdf_url)

        # Step 7 — tandai selesai
        _set_job(job_id, {
            "status":            JobStatus.DONE,
            "step":              "Selesai",
            "nama_siswa":        data["nama_siswa"],
            "kelas":             data["kelas"],
            "mata_pelajaran":    data["mata_pelajaran"],
            "readability_score": readability,
            "wcag_score":        wcag,
            "profiling":         profiling_out,
            "adaptive":          adaptive_out,
            "insight":           insight_out,
            "pdf_url":           pdf_url,
            "pdf_local":         pdf_path,
            "finished_at":       datetime.now().isoformat(),
        })
        log.info("Job %s selesai. Readability=%s WCAG=%s", job_id, readability, wcag)

    except Exception as exc:
        log.exception("Job %s gagal: %s", job_id, exc)
        _update_job(job_id, {
            "status": JobStatus.FAILED,
            "step":   "Gagal",
            "error":  str(exc),
        })


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class JobCreatedResponse(BaseModel):
    job_id:  str
    message: str = "Pipeline AI dimulai. Gunakan job_id untuk cek status."


class StatusResponse(BaseModel):
    job_id:  str
    status:  str
    step:    str


class ResultResponse(BaseModel):
    job_id:             str
    status:             str
    nama_siswa:         str
    kelas:              str
    mata_pelajaran:     str
    readability_score:  int
    wcag_score:         int
    profiling:          str
    adaptive:           str
    insight:            str
    pdf_url:            Optional[str] = None
    finished_at:        str


class HealthResponse(BaseModel):
    status:     str
    redis:      bool
    s3:         bool
    timestamp:  str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Cek status semua dependency",
)
def health_check():
    return HealthResponse(
        status="ok",
        redis=REDIS_ENABLED,
        s3=bool(S3_BUCKET and _s3),
        timestamp=datetime.now().isoformat(),
    )


@app.post(
    "/api/rpp/generate",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["RPP"],
    summary="Mulai generate RPP Inklusif",
    description=(
        "Kirim data siswa dan (opsional) file materi dalam format `.docx` atau `.pdf`. "
        "Proses AI berjalan di background. Gunakan `job_id` yang dikembalikan untuk cek status."
    ),
    dependencies=[Depends(verify_api_key)],
)
async def generate_rpp(
    nama_siswa:     str            = Form(..., description="Nama lengkap siswa"),
    kelas:          str            = Form(..., description="Kelas siswa, contoh: 2 SD"),
    mata_pelajaran: str            = Form(..., description="Mata pelajaran, contoh: Bahasa Indonesia"),
    gejala:         str            = Form(..., description="Kondisi/gejala siswa, contoh: susah fokus, ADHD"),
    materi_mentah:  str            = Form("",  description="Teks materi mentah (opsional jika upload file)"),
    file: Optional[UploadFile]     = File(None, description="File materi .docx atau .pdf (opsional)"),
):
    doc_bytes: Optional[bytes] = None
    doc_ext:   Optional[str]   = None

    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in {".docx", ".pdf"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Format file tidak didukung. Gunakan .docx atau .pdf.",
            )
        doc_bytes = await file.read()
        doc_ext   = ext
        log.info("File diterima: %s (%d bytes)", file.filename, len(doc_bytes))

    if not materi_mentah and not doc_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sertakan materi_mentah (teks) atau upload file dokumen.",
        )

    job_id = str(uuid.uuid4())
    data   = {
        "nama_siswa":     nama_siswa,
        "kelas":          kelas,
        "mata_pelajaran": mata_pelajaran,
        "gejala":         gejala,
        "materi_mentah":  materi_mentah,
    }

    _set_job(job_id, {
        "status":     JobStatus.QUEUED,
        "step":       "Antri...",
        "nama_siswa": nama_siswa,
        "created_at": datetime.now().isoformat(),
    })

    threading.Thread(
        target=_run_pipeline,
        args=(job_id, data, doc_bytes, doc_ext),
        daemon=True,
    ).start()

    log.info("Job %s dibuat untuk siswa '%s'", job_id, nama_siswa)
    return JobCreatedResponse(job_id=job_id)


@app.get(
    "/api/rpp/status/{job_id}",
    response_model=StatusResponse,
    tags=["RPP"],
    summary="Cek progress pipeline (untuk loading animation)",
    dependencies=[Depends(verify_api_key)],
)
def get_status(job_id: str):
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return StatusResponse(
        job_id=job_id,
        status=job.get("status", "unknown"),
        step=job.get("step", ""),
    )


@app.get(
    "/api/rpp/result/{job_id}",
    response_model=ResultResponse,
    tags=["RPP"],
    summary="Ambil hasil evaluasi RPP (readability score, WCAG, output agent)",
    dependencies=[Depends(verify_api_key)],
)
def get_result(job_id: str):
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")

    if job.get("status") == JobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline gagal: {job.get('error', 'unknown error')}",
        )

    if job.get("status") != JobStatus.DONE:
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail=f"Job belum selesai. Status: {job.get('status')} — {job.get('step')}",
        )

    return ResultResponse(
        job_id=job_id,
        status=job["status"],
        nama_siswa=job.get("nama_siswa", ""),
        kelas=job.get("kelas", ""),
        mata_pelajaran=job.get("mata_pelajaran", ""),
        readability_score=job.get("readability_score", 0),
        wcag_score=job.get("wcag_score", 0),
        profiling=job.get("profiling", ""),
        adaptive=job.get("adaptive", ""),
        insight=job.get("insight", ""),
        pdf_url=job.get("pdf_url"),
        finished_at=job.get("finished_at", ""),
    )


@app.get(
    "/api/rpp/download/{job_id}",
    tags=["RPP"],
    summary="Download PDF RPP Inklusif",
    dependencies=[Depends(verify_api_key)],
)
def download_pdf(job_id: str):
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    if job.get("status") != JobStatus.DONE:
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail="PDF belum siap. Tunggu hingga status DONE.",
        )

    # Kalau ada di S3 → redirect ke presigned URL
    if job.get("pdf_url"):
        return RedirectResponse(url=job["pdf_url"])

    # Fallback: stream dari local disk
    pdf_path = job.get("pdf_local", "")
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="File PDF tidak ditemukan di server.")

    filename = os.path.basename(pdf_path)

    def _iter_file():
        with open(pdf_path, "rb") as f:
            yield from f

    return StreamingResponse(
        _iter_file(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
