<div align="center">

# ASIQ — Adaptive Student Inclusive Learning

**Sistem Pembuat RPP Inklusif Berbasis AI untuk Siswa Berkebutuhan Khusus**

Capstone Project · Universitas Brawijaya · 2026

</div>

---

## Deskripsi

ASIQ adalah sistem berbasis kecerdasan buatan yang membantu guru membuat **Rencana Pelaksanaan Pembelajaran (RPP) Inklusif** yang diadaptasi secara otomatis sesuai kondisi dan kebutuhan khusus setiap siswa (ADHD, Disleksia, Autisme, Slow Learner, dll.).

Sistem ini menggunakan pipeline **3 AI Agent** yang bekerja secara sekuensial:

1. **Profiling Agent** — Menganalisis kondisi siswa dan menyusun strategi adaptasi berdasarkan pedoman WCAG & Permendikbud (via RAG)
2. **Adaptive Agent** — Menulis ulang dan menyederhanakan materi sesuai strategi profiling
3. **Insight Agent** — Mengaudit inklusivitas materi dan memberikan **Readability Score** serta **WCAG/Inclusivity Score** (0–100)

Output akhir berupa **PDF RPP Inklusif** dengan ilustrasi AI yang siap digunakan guru di kelas.

---

## Arsitektur Sistem

```
Input Guru (data siswa + materi)
        │
        ├── CLI (main.py)
        └── REST API (api.py)
                │
                ▼
┌─────────────────────────────────────────────┐
│              CrewAI Pipeline                │
│                                             │
│  Agent 1: Profiling Agent                  │
│    └── cari_pedoman (RAG)     ◄─────────┐  │
│    └── cek_cache_profiling               │  │
│    └── simpan_cache_profiling            │  │
│                                          │  │
│  Agent 2: Adaptive Agent                 │  │
│    └── cari_pedoman (RAG)     ◄─────────┤  │
│                                          │  │
│  Agent 3: Insight Agent                  │  │
│    (evaluation only — no tools)          │  │
│                                          │  │
└──────────────┬───────────────────────────┘  │
               │                              │
               │         ┌────────────────────┘
               │         │
               ▼         ▼
    ┌────────────────┐  ┌──────────────────┐
    │   ChromaDB     │  │  Redis Cache     │
    │ (WCAG,         │  │ (strategi per    │
    │  Permendikbud) │  │  diagnosis, TTL) │
    └────────────────┘  └──────────────────┘
               │
               ▼
    ┌──────────────────────────────┐
    │     Generate Output          │
    │  - PDF RPP Inklusif          │
    │  - 3 file Markdown           │
    │  - Illustrasi AI (Pollinations)│
    └──────────┬───────────────────┘
               │
               ▼
    ┌──────────────────────────────┐
    │      Persistence Layer       │
    │  - PostgreSQL (job history)  │
    │  - Redis (job state)         │
    │  - Amazon S3 (PDF storage)   │
    └──────────────────────────────┘
```

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| **AI Orchestration** | CrewAI |
| **LLM (Primary)** | OpenRouter · `openai/gpt-oss-120b` |
| **LLM (Fallback)** | Groq API · `openai/gpt-oss-120b` (free tier) |
| **LLM Abstraction** | LiteLLM |
| **Embedding Model** | HuggingFace · `intfloat/multilingual-e5-base` |
| **Vector Database** | ChromaDB (embedded) |
| **Relational Database** | PostgreSQL (Amazon RDS) |
| **Cache** | Redis (Amazon ElastiCache) |
| **PDF Generator** | ReportLab (Platypus multi-page layout) |
| **Ilustrasi AI** | Pollinations.ai |
| **REST API** | FastAPI + Uvicorn |
| **Cloud** | Amazon EC2 · RDS · ElastiCache · S3 |
| **Integrasi** | LangChain (embedding wrapper + ChromaDB) |

---

## Struktur Folder

```
SetupVectorDatabase/
├── config/
│   ├── agents.yaml          # Konfigurasi persona tiap agent
│   └── tasks.yaml           # Konfigurasi tugas tiap agent
├── deploy/
│   ├── setup.sh             # Setup script EC2 Ubuntu 22.04
│   ├── asiq.service         # Systemd service untuk production
│   └── nginx.conf           # Reverse proxy + SSL (Nginx)
├── knowledge/               # Folder PDF pedoman inklusif (WCAG, Permendikbud) — tidak di-push
├── input/                   # Folder dokumen materi guru (.docx / .pdf) — tidak di-push
├── output/                  # Hasil generate RPP — tidak di-push
├── database/                # Data ChromaDB lokal — tidak di-push
├── assets/
│   ├── emoji_cache/         # Twemoji PNG (auto-download saat generate PDF)
│   └── img_cache/           # Illustrasi dari Pollinations.ai
├── api.py                   # REST API endpoints (FastAPI)
├── crew.py                  # Definisi agent, tools, dan crew pipeline
├── main.py                  # Entry point CLI & PDF generator
├── db_connection.py         # Koneksi PostgreSQL pool & Redis client
├── ingest_pedoman.py        # Ingest PDF pedoman ke ChromaDB + PostgreSQL
├── init_chroma.py           # Inisialisasi ChromaDB dengan data referensi awal
├── test_pdf.py              # Test generate PDF tanpa menjalankan AI
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Instalasi & Setup

### 1. Clone Repository

```bash
git clone https://github.com/Capstone-Jalin-Mayantara/SetupVectorDatabase.git
cd SetupVectorDatabase
```

### 2. Buat Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / Mac
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Konfigurasi Environment Variables

Salin file contoh dan isi dengan nilai yang sesuai:

```bash
cp .env.example .env
```

Buka `.env` dan isi sesuai kebutuhan (lihat bagian [Environment Variables](#environment-variables) di bawah).

### 5. Siapkan Folder & Dokumen Pedoman

```bash
mkdir knowledge input
```

- Masukkan file PDF pedoman inklusif (WCAG, Permendikbud, dll.) ke folder `knowledge/`
- Masukkan dokumen materi guru (`.docx` / `.pdf`) ke folder `input/`

### 6. Inisialisasi Vector Database

```bash
# Opsi A — Inisialisasi cepat dengan 2 dokumen referensi dummy (untuk testing lokal)
python init_chroma.py

# Opsi B — Ingest penuh semua PDF dari folder knowledge/ (untuk production)
python ingest_pedoman.py
```

---

## Menjalankan Sistem

### Mode CLI (Interaktif)

```bash
python main.py
```

Sistem akan meminta input:
- Nama siswa, kelas, mata pelajaran, gejala/kondisi
- Pilih sumber materi: dokumen dari `input/` atau input teks manual

### Mode Development (Skip Input Manual)

Di `main.py`, ubah:
```python
DEV_MODE = True
```

Sistem otomatis menggunakan data dummy dan dokumen pertama dari folder `input/`.

### Mode REST API

```bash
uvicorn api:app --reload --port 8000
```

API tersedia di `http://localhost:8000`. Lihat bagian [REST API Endpoints](#rest-api-endpoints) di bawah.

### Test PDF Tanpa AI

Untuk mengecek layout PDF tanpa menjalankan pipeline AI:

```bash
python test_pdf.py
```

---

## REST API Endpoints

Semua endpoint (kecuali `/health`) memerlukan header:
```
X-API-Key: <nilai API_KEY dari .env>
```

| Method | Path | Deskripsi |
|--------|------|-----------|
| `GET` | `/health` | Cek status Redis, S3, dan PostgreSQL |
| `POST` | `/api/rpp/generate` | Generate RPP untuk 1 siswa (async) |
| `POST` | `/api/rpp/batch` | Batch generate hingga 10 siswa sekaligus |
| `GET` | `/api/rpp/batch/{batch_id}/status` | Cek progress semua job dalam satu batch |
| `GET` | `/api/rpp/status/{job_id}` | Cek status satu job |
| `GET` | `/api/rpp/result/{job_id}` | Ambil hasil lengkap RPP + skor |
| `GET` | `/api/rpp/download/{job_id}` | Download PDF (redirect S3 atau stream lokal) |
| `POST` | `/api/admin/backup-chroma` | Backup ChromaDB ke S3 |

### Contoh: Generate RPP (Single)

```bash
curl -X POST http://localhost:8000/api/rpp/generate \
  -H "X-API-Key: your_api_key" \
  -F "nama_siswa=Budi Santoso" \
  -F "kelas=2 SD" \
  -F "mata_pelajaran=Bahasa Indonesia" \
  -F "gejala=Disleksia" \
  -F "file=@materi.docx"
```

Response `202 Accepted`:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Pipeline AI dimulai..."
}
```

### Contoh: Cek Status

```bash
curl http://localhost:8000/api/rpp/status/550e8400-... \
  -H "X-API-Key: your_api_key"
```

```json
{
  "job_id": "550e8400-...",
  "status": "processing",
  "step": "Agent 2: Adaptasi materi..."
}
```

### Contoh: Ambil Hasil

```bash
curl http://localhost:8000/api/rpp/result/550e8400-... \
  -H "X-API-Key: your_api_key"
```

```json
{
  "job_id": "550e8400-...",
  "status": "done",
  "nama_siswa": "Budi Santoso",
  "kelas": "2 SD",
  "mata_pelajaran": "Bahasa Indonesia",
  "readability_score": 87,
  "wcag_score": 92,
  "profiling": "Strategi adaptasi...",
  "adaptive": "Materi final...",
  "insight": "Laporan audit...",
  "pdf_url": "https://s3.ap-southeast-1.amazonaws.com/..."
}
```

### Job Status Lifecycle

```
QUEUED → PROCESSING → DONE
                   ↘ FAILED
```

---

## Output

Setiap run menghasilkan folder `output/YYYYMMDD_HHMMSS_NamaSiswa/` berisi:

| File | Isi |
|---|---|
| `01_Strategi_Profiling.md` | Strategi adaptasi dari Agent 1 |
| `02_Materi_Adaptif.md` | Materi yang sudah diadaptasi dari Agent 2 |
| `03_Laporan_Audit.md` | Laporan audit inklusivitas dari Agent 3 |
| `RPP_Inklusif_NamaSiswa_timestamp.pdf` | PDF RPP siap pakai (cover + konten + ilustrasi) |

---

## Environment Variables

Salin `.env.example` ke `.env` dan isi nilai berikut:

### LLM

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `GROQ_API_KEY` | Ya (jika tanpa OpenRouter) | — | API key Groq free tier |
| `OPENROUTER_API_KEY` | Tidak | `""` | Jika diisi, digunakan sebagai LLM utama (tanpa delay Groq) |

### Database — PostgreSQL (Amazon RDS)

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `DB_HOST` | Tidak | — | RDS endpoint |
| `DB_NAME` | Tidak | `asiq_db` | Nama database |
| `DB_USER` | Tidak | `postgres` | Username |
| `DB_PASSWORD` | Tidak | — | Password |
| `DB_PORT` | Tidak | `5432` | Port |
| `DB_POOL_MIN` | Tidak | `1` | Min koneksi pool |
| `DB_POOL_MAX` | Tidak | `5` | Max koneksi pool |
| `DB_CONNECT_TIMEOUT` | Tidak | `5` | Timeout koneksi (detik) |

> Jika tidak diisi, sistem tetap berjalan tanpa riwayat job di PostgreSQL.

### Cache — Redis (Amazon ElastiCache)

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `REDIS_HOST` | Tidak | — | Redis endpoint |
| `REDIS_PORT` | Tidak | `6379` | Port |
| `REDIS_SSL` | Tidak | `false` | **Wajib `true`** untuk ElastiCache Serverless |

> Jika tidak diisi, job state disimpan di memory (hilang saat restart).

### Storage — Amazon S3

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `S3_BUCKET` | Tidak | — | Nama bucket untuk simpan PDF hasil |
| `AWS_REGION` | Tidak | `ap-southeast-1` | Region AWS |

> Jika tidak diisi, PDF disimpan lokal di folder `output/`.

### REST API

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `API_KEY` | Ya | — | Secret key untuk header `X-API-Key` |
| `ALLOWED_ORIGINS` | Tidak | `*` | CORS origins, pisah koma |
| `JOB_TTL_SECONDS` | Tidak | `86400` | Durasi job di Redis (24 jam) |

### Batch Processing

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `BATCH_MAX_WORKERS` | Tidak | `2` | Pipeline paralel (jangan > 2 jika pakai Groq) |
| `BATCH_MAX_STUDENTS` | Tidak | `10` | Max siswa per request batch |

### Groq Rate Limiting

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `GROQ_TASK_DELAY` | Tidak | `30` | Delay antar task (detik). Set `0` jika pakai OpenRouter |
| `GROQ_STEP_DELAY` | Tidak | `8` | Delay antar step (detik) |
| `GROQ_MAX_RETRIES` | Tidak | `3` | Retry otomatis saat kena rate limit 429 |

### Document Processing

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `MATERI_MAX_CHARS` | Tidak | `12000` | Batas karakter dokumen materi sebelum dipotong |

### Image Generation

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `POLLINATIONS_TOKEN` | Tidak | `""` | Bearer token Pollinations.ai untuk ilustrasi PDF |

---

## Deployment (Production — Amazon EC2)

### Persiapan

```bash
# Clone di server EC2
git clone https://github.com/Capstone-Jalin-Mayantara/SetupVectorDatabase.git
cd SetupVectorDatabase

# Jalankan setup script (Ubuntu 22.04)
chmod +x deploy/setup.sh
./deploy/setup.sh
```

Script `setup.sh` akan otomatis:
1. Install Python 3.10, Nginx, Certbot
2. Buat virtual environment + install dependencies
3. Inisialisasi ChromaDB
4. Ingest PDF dari folder `knowledge/` (jika ada)
5. Install systemd service `asiq.service`
6. Konfigurasi Nginx reverse proxy + SSL

### Kelola Service

```bash
# Start / stop / restart
sudo systemctl start asiq
sudo systemctl stop asiq
sudo systemctl restart asiq

# Cek status
sudo systemctl status asiq

# Lihat log real-time
journalctl -u asiq -f
```

### Catatan Security Group AWS

- Port **22** (SSH) — batasi ke IP Anda
- Port **80** & **443** (HTTP/HTTPS) — buka ke `0.0.0.0/0`
- Port **8000** (Uvicorn) — **jangan** buka ke publik (akses via Nginx saja)
- **Redis ElastiCache Serverless** — wajib set `REDIS_SSL=true`

---

## Error Handling & Graceful Fallback

| Dependency | Status DOWN | Perilaku Sistem |
|---|---|---|
| **Redis** | DOWN | Cache dinonaktifkan, fallback ke memory dict + PostgreSQL |
| **PostgreSQL** | DOWN | Job state di Redis/memory saja, riwayat hilang saat restart |
| **S3** | DOWN | PDF disimpan lokal di `output/`, skip upload |
| **ChromaDB** | DOWN | Pipeline gagal (RAG tidak tersedia) |
| **Groq API (rate limit)** | 429 | Retry hingga 3x dengan exponential backoff |
| **Pollinations** | DOWN | PDF dibuat tanpa ilustrasi, pipeline tetap lanjut |
| **GPU/CUDA** | Tidak ada | Embedding berjalan di CPU (lebih lambat) |

---

## Catatan Teknis

- **LLM Model** yang digunakan: `openai/gpt-oss-120b` via OpenRouter atau Groq
- **GPU (CUDA) disarankan** untuk embedding model `intfloat/multilingual-e5-base` (~480M params, butuh ~2GB VRAM)
- **Groq free tier** memiliki limit TPM 8.000 dan TPD 500.000 — sistem sudah dilengkapi delay otomatis (30 detik antar task, 8 detik antar step)
- **OpenRouter** disarankan untuk production (tanpa rate limit ketat, set `GROQ_TASK_DELAY=0`)
- **Redis ElastiCache Serverless** wajib menggunakan TLS (`REDIS_SSL=true`)
- **Dokumen materi** dipotong otomatis di 12.000 karakter untuk menjaga penggunaan token LLM

---

## Anggota Kelompok

| NIM | Nama |
|---|---|
| 235150207111002 | Bintang Ula Nur Maghfirow |
| 235150207111067 | Anak Agung Ngurah Aditya Wirayudha |
| 235150407111027 | Bram Oktavian Ramadhan |
| 235150707111057 | Bagus Setiawan |
| 235150707111029 | Andrean Noviandi |
| 235150201111046 | Muhammad Rifki Akbar |

---

<div align="center">

Universitas Brawijaya · Fakultas Ilmu Komputer · Capstone Project 2026

</div>
