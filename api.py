"""
ASIQ — Production REST API
Jalankan di EC2: uvicorn api:app --host 0.0.0.0 --port 8000 --workers 1
Docs tersedia di: http://<EC2_IP>:8000/docs

Environment variables wajib (lihat .env.example):
  GROQ_API_KEY, API_KEY, S3_BUCKET, DB_HOST, REDIS_HOST
"""

import io
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

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

API_KEY            = os.getenv("API_KEY", "")
S3_BUCKET          = os.getenv("S3_BUCKET", "")
AWS_REGION         = os.getenv("AWS_REGION", "ap-southeast-1")
JOB_TTL_SECONDS    = int(os.getenv("JOB_TTL_SECONDS", 86400))   # 24 jam
ALLOWED_ORIGINS    = os.getenv("ALLOWED_ORIGINS", "*").split(",")
BATCH_MAX_WORKERS  = int(os.getenv("BATCH_MAX_WORKERS", "2"))    # max pipeline bersamaan
BATCH_MAX_STUDENTS = int(os.getenv("BATCH_MAX_STUDENTS", "10"))  # max siswa per batch


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


# ── Thread pool untuk batch processing ───────────────────────────────────────
# Batasi berapa pipeline AI yang boleh berjalan bersamaan agar tidak throttle Groq.

_batch_executor = ThreadPoolExecutor(max_workers=BATCH_MAX_WORKERS)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="ASIQ API",
    description=(
        "**Adaptive Student Inclusive Learning** — REST API untuk generate "
        "RPP Inklusif berbasis AI.\n\n"
        "Semua endpoint (kecuali `/health`) membutuhkan header `X-API-Key`."
    ),
    version="1.1.0",
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


# ── Job storage helpers (Redis + PostgreSQL + memory fallback) ─────────────────
# Hierarki persistensi:
#   1. Redis (cepat, TTL-based) → untuk polling status real-time
#   2. PostgreSQL (permanen) → untuk history & survive restart
#   3. Memory dict (fallback lokal) → kalau Redis dan PG tidak tersedia

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
        if raw:
            return json.loads(raw)
    # Fallback ke memory
    if job_id in _memory_store:
        return _memory_store[job_id]
    # Fallback terakhir: cek PostgreSQL (untuk job setelah restart)
    return _load_job_from_postgres(job_id)


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
        log.info("Upload S3 selesai: %s", s3_key)
        return url
    except ClientError as e:
        log.error("Gagal upload S3: %s", e)
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


# ── PostgreSQL helpers ────────────────────────────────────────────────────────

def _ensure_tables():
    """Buat tabel jika belum ada. Dipanggil sekali saat startup."""
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
                gejala         TEXT,
                readability    INT DEFAULT 0,
                wcag_score     INT DEFAULT 0,
                pdf_url        TEXT,
                status         TEXT DEFAULT 'queued',
                profiling_out  TEXT,
                adaptive_out   TEXT,
                insight_out    TEXT,
                pdf_local      TEXT,
                error_msg      TEXT,
                batch_id       TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at    TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rpp_batches (
                batch_id    TEXT PRIMARY KEY,
                total       INT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.warning("PostgreSQL tidak tersedia, skip buat tabel: %s", e)


def _save_job_to_postgres(job_id: str, data: dict) -> None:
    try:
        from db_connection import get_postgres_connection
        conn   = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO rpp_jobs
                (job_id, nama_siswa, kelas, mata_pelajaran, gejala, readability,
                 wcag_score, pdf_url, status, profiling_out, adaptive_out,
                 insight_out, pdf_local, error_msg, batch_id, finished_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (job_id) DO UPDATE SET
                readability   = EXCLUDED.readability,
                wcag_score    = EXCLUDED.wcag_score,
                pdf_url       = EXCLUDED.pdf_url,
                status        = EXCLUDED.status,
                profiling_out = EXCLUDED.profiling_out,
                adaptive_out  = EXCLUDED.adaptive_out,
                insight_out   = EXCLUDED.insight_out,
                pdf_local     = EXCLUDED.pdf_local,
                error_msg     = EXCLUDED.error_msg,
                finished_at   = EXCLUDED.finished_at
        """, (
            job_id,
            data.get("nama_siswa", ""),
            data.get("kelas", ""),
            data.get("mata_pelajaran", ""),
            data.get("gejala", ""),
            data.get("readability_score", 0),
            data.get("wcag_score", 0),
            data.get("pdf_url"),
            data.get("status", "queued"),
            data.get("profiling", ""),
            data.get("adaptive", ""),
            data.get("insight", ""),
            data.get("pdf_local"),
            data.get("error"),
            data.get("batch_id"),
            datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None,
        ))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.warning("Gagal simpan job %s ke PostgreSQL: %s", job_id, e)


def _load_job_from_postgres(job_id: str) -> Optional[dict]:
    """Fallback load job dari PostgreSQL (dipakai setelah restart Redis/server)."""
    try:
        from db_connection import get_postgres_connection
        conn   = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT nama_siswa, kelas, mata_pelajaran, gejala, readability, "
            "wcag_score, pdf_url, status, profiling_out, adaptive_out, "
            "insight_out, pdf_local, error_msg, batch_id, finished_at "
            "FROM rpp_jobs WHERE job_id = %s",
            (job_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            return None
        (nama_siswa, kelas, mapel, gejala, readability, wcag, pdf_url,
         job_status, profiling, adaptive, insight, pdf_local, error,
         batch_id, finished_at) = row
        return {
            "job_id": job_id, "nama_siswa": nama_siswa, "kelas": kelas,
            "mata_pelajaran": mapel, "gejala": gejala,
            "readability_score": readability or 0, "wcag_score": wcag or 0,
            "pdf_url": pdf_url, "status": job_status,
            "profiling": profiling or "", "adaptive": adaptive or "",
            "insight": insight or "", "pdf_local": pdf_local,
            "error": error, "batch_id": batch_id,
            "finished_at": finished_at.isoformat() if finished_at else "",
            "step": "Selesai" if job_status == JobStatus.DONE else "Gagal",
        }
    except Exception:
        return None


# ── Background pipeline ───────────────────────────────────────────────────────

def _run_pipeline(job_id: str, data: dict, doc_bytes: Optional[bytes], doc_ext: Optional[str]) -> None:
    try:
        from main import _create_output_dir, _load_document, _save_markdown_files, generate_pdf
        from crew import run_crew_with_retry

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

        # Step 2 — jalankan crew AI (dengan retry otomatis jika rate-limited)
        _update_job(job_id, {"step": "Agent 1: Profiling siswa..."})
        profil = (
            f"Nama: {data['nama_siswa']} | Kelas: {data['kelas']} | "
            f"Mata Pelajaran: {data['mata_pelajaran']} | Kondisi/Gejala: {data['gejala']}"
        )

        hasil = run_crew_with_retry(inputs={
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

        # Step 6 — tandai selesai & simpan ke Redis + PostgreSQL
        finished_data = {
            "status":            JobStatus.DONE,
            "step":              "Selesai",
            "nama_siswa":        data["nama_siswa"],
            "kelas":             data["kelas"],
            "mata_pelajaran":    data["mata_pelajaran"],
            "gejala":            data.get("gejala", ""),
            "readability_score": readability,
            "wcag_score":        wcag,
            "profiling":         profiling_out,
            "adaptive":          adaptive_out,
            "insight":           insight_out,
            "pdf_url":           pdf_url,
            "pdf_local":         pdf_path,
            "batch_id":          data.get("batch_id"),
            "finished_at":       datetime.now().isoformat(),
        }
        _set_job(job_id, finished_data)
        _save_job_to_postgres(job_id, finished_data)
        log.info("Job %s selesai. Readability=%s WCAG=%s", job_id, readability, wcag)

    except Exception as exc:
        log.exception("Job %s gagal: %s", job_id, exc)
        failed_data = {
            "status":    JobStatus.FAILED,
            "step":      "Gagal",
            "error":     str(exc),
            "batch_id":  data.get("batch_id"),
            "nama_siswa": data.get("nama_siswa", ""),
        }
        _update_job(job_id, failed_data)
        _save_job_to_postgres(job_id, {**failed_data, **data})


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    _ensure_tables()
    log.info("ASIQ API siap. Redis=%s S3=%s BatchWorkers=%d",
             REDIS_ENABLED, bool(_s3), BATCH_MAX_WORKERS)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class StudentInput(BaseModel):
    nama_siswa:     str = Field(..., description="Nama lengkap siswa")
    kelas:          str = Field(..., description="Kelas siswa, contoh: 2 SD")
    mata_pelajaran: str = Field(..., description="Mata pelajaran, contoh: Bahasa Indonesia")
    gejala:         str = Field(..., description="Kondisi/gejala siswa, contoh: susah fokus, ADHD")
    materi_mentah:  str = Field(..., description="Teks materi pembelajaran mentah")


class BatchRequest(BaseModel):
    students: List[StudentInput] = Field(
        ...,
        min_length=1,
        description="Daftar siswa yang akan dibuatkan RPP-nya sekaligus (maks 10)",
    )


class JobCreatedResponse(BaseModel):
    job_id:  str
    message: str = "Pipeline AI dimulai. Gunakan job_id untuk cek status."


class BatchCreatedResponse(BaseModel):
    batch_id: str
    job_ids:  List[str]
    total:    int
    message:  str = "Batch berhasil dibuat. Semua job diproses bersamaan."


class StatusResponse(BaseModel):
    job_id:  str
    status:  str
    step:    str


class BatchStatusResponse(BaseModel):
    batch_id: str
    total:    int
    done:     int
    failed:   int
    pending:  int
    jobs:     List[dict]


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
    status:       str
    redis:        bool
    s3:           bool
    postgres:     bool
    timestamp:    str


class BackupResponse(BaseModel):
    message:  str
    s3_key:   Optional[str] = None
    size_mb:  float


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Cek status semua dependency",
)
def health_check():
    pg_ok = False
    try:
        from db_connection import get_postgres_connection
        conn = get_postgres_connection()
        conn.close()
        pg_ok = True
    except Exception:
        pass
    return HealthResponse(
        status="ok",
        redis=REDIS_ENABLED,
        s3=bool(S3_BUCKET and _s3),
        postgres=pg_ok,
        timestamp=datetime.now().isoformat(),
    )


@app.post(
    "/api/rpp/generate",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["RPP"],
    summary="Generate RPP Inklusif untuk 1 siswa",
    description=(
        "Kirim data siswa dan (opsional) file materi `.docx` atau `.pdf`. "
        "Proses AI berjalan di background. Gunakan `job_id` untuk polling status."
    ),
    dependencies=[Depends(verify_api_key)],
)
async def generate_rpp(
    nama_siswa:     str           = Form(...),
    kelas:          str           = Form(...),
    mata_pelajaran: str           = Form(...),
    gejala:         str           = Form(...),
    materi_mentah:  str           = Form(""),
    file: Optional[UploadFile]    = File(None),
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

    if not materi_mentah and not doc_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sertakan materi_mentah (teks) atau upload file dokumen.",
        )

    job_id = str(uuid.uuid4())
    data   = {
        "nama_siswa": nama_siswa, "kelas": kelas,
        "mata_pelajaran": mata_pelajaran, "gejala": gejala,
        "materi_mentah": materi_mentah,
    }

    _set_job(job_id, {
        "status": JobStatus.QUEUED, "step": "Antri...",
        "nama_siswa": nama_siswa, "created_at": datetime.now().isoformat(),
    })
    threading.Thread(target=_run_pipeline, args=(job_id, data, doc_bytes, doc_ext), daemon=True).start()
    log.info("Job %s dibuat untuk '%s'", job_id, nama_siswa)
    return JobCreatedResponse(job_id=job_id)


@app.post(
    "/api/rpp/batch",
    response_model=BatchCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Batch"],
    summary="Generate RPP untuk banyak siswa sekaligus",
    description=(
        "Kirim JSON berisi daftar siswa (maks 10). "
        f"Sistem memproses maksimal {BATCH_MAX_WORKERS} siswa secara paralel untuk menghindari "
        "throttle API. Gunakan `batch_id` atau masing-masing `job_id` untuk cek progress."
    ),
    dependencies=[Depends(verify_api_key)],
)
async def batch_generate_rpp(req: BatchRequest):
    if len(req.students) > BATCH_MAX_STUDENTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maksimal {BATCH_MAX_STUDENTS} siswa per batch.",
        )

    batch_id = str(uuid.uuid4())
    job_ids  = []
    now      = datetime.now().isoformat()

    for student in req.students:
        job_id = str(uuid.uuid4())
        job_ids.append(job_id)
        data = {
            "nama_siswa": student.nama_siswa, "kelas": student.kelas,
            "mata_pelajaran": student.mata_pelajaran, "gejala": student.gejala,
            "materi_mentah": student.materi_mentah, "batch_id": batch_id,
        }
        _set_job(job_id, {
            "status": JobStatus.QUEUED, "step": "Antri (batch)...",
            "nama_siswa": student.nama_siswa, "batch_id": batch_id,
            "created_at": now,
        })
        # Submit ke thread pool — max BATCH_MAX_WORKERS berjalan bersamaan
        _batch_executor.submit(_run_pipeline, job_id, data, None, None)

    _set_job(f"batch:{batch_id}", {
        "batch_id": batch_id, "job_ids": job_ids,
        "total": len(job_ids), "created_at": now,
    })

    # Simpan batch ke PostgreSQL
    try:
        from db_connection import get_postgres_connection
        conn   = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO rpp_batches (batch_id, total) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (batch_id, len(job_ids)),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        log.warning("Gagal simpan batch ke PostgreSQL: %s", e)

    log.info("Batch %s dibuat: %d siswa", batch_id, len(job_ids))
    return BatchCreatedResponse(
        batch_id=batch_id, job_ids=job_ids, total=len(job_ids),
    )


@app.get(
    "/api/rpp/batch/{batch_id}/status",
    response_model=BatchStatusResponse,
    tags=["Batch"],
    summary="Cek progress semua job dalam satu batch",
    dependencies=[Depends(verify_api_key)],
)
def get_batch_status(batch_id: str):
    batch = _get_job(f"batch:{batch_id}")
    if not batch:
        raise HTTPException(status_code=404, detail="Batch tidak ditemukan.")

    job_ids = batch.get("job_ids", [])
    jobs_summary = []
    done = failed = pending = 0

    for jid in job_ids:
        job = _get_job(jid) or {}
        s = job.get("status", "unknown")
        jobs_summary.append({
            "job_id":     jid,
            "nama_siswa": job.get("nama_siswa", ""),
            "status":     s,
            "step":       job.get("step", ""),
        })
        if s == JobStatus.DONE:
            done += 1
        elif s == JobStatus.FAILED:
            failed += 1
        else:
            pending += 1

    return BatchStatusResponse(
        batch_id=batch_id, total=len(job_ids),
        done=done, failed=failed, pending=pending,
        jobs=jobs_summary,
    )


@app.get(
    "/api/rpp/status/{job_id}",
    response_model=StatusResponse,
    tags=["RPP"],
    summary="Cek progress pipeline satu job",
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
    summary="Ambil hasil RPP lengkap setelah pipeline selesai",
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

    if job.get("pdf_url"):
        return RedirectResponse(url=job["pdf_url"])

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


@app.post(
    "/api/admin/backup-chroma",
    response_model=BackupResponse,
    tags=["Admin"],
    summary="Backup ChromaDB ke S3",
    description=(
        "Zip seluruh folder database/chroma_db dan upload ke S3. "
        "Jalankan secara rutin (misal: cron harian) untuk mencegah kehilangan data vector."
    ),
    dependencies=[Depends(verify_api_key)],
)
def backup_chroma():
    db_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "chroma_db")
    if not os.path.exists(db_dir):
        raise HTTPException(status_code=404, detail="Folder ChromaDB tidak ditemukan.")

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp_zip   = os.path.join(tempfile.gettempdir(), f"chroma_backup_{timestamp}")
        zip_path  = shutil.make_archive(tmp_zip, "zip", db_dir)
        size_mb   = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
        log.info("ChromaDB di-zip: %s (%.2f MB)", zip_path, size_mb)

        s3_key = None
        if _s3 and S3_BUCKET:
            s3_key = f"backups/chroma_{timestamp}.zip"
            _upload_to_s3(zip_path, s3_key)
            os.unlink(zip_path)
            return BackupResponse(
                message=f"Backup berhasil diunggah ke S3.",
                s3_key=s3_key,
                size_mb=size_mb,
            )
        else:
            return BackupResponse(
                message=f"S3 tidak tersedia. Backup tersimpan lokal di: {zip_path}",
                s3_key=None,
                size_mb=size_mb,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backup gagal: {e}")
