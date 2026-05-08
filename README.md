<div align="center">

# ASIQ — Adaptive Student Inclusive Learning

**Sistem Pembuat RPP Inklusif Berbasis AI untuk Siswa Berkebutuhan Khusus**

Capstone Project · Universitas Brawijaya · 2026

</div>

---

## Deskripsi

ASIQ adalah sistem berbasis kecerdasan buatan yang membantu guru membuat **Rencana Pelaksanaan Pembelajaran (RPP) Inklusif** yang diadaptasi secara otomatis sesuai kondisi dan kebutuhan khusus setiap siswa (ADHD, Disleksia, Autisme, Slow Learner, dll.).

Sistem ini menggunakan pipeline **3 AI Agent** yang bekerja secara sekuensial:
1. **Profiling Agent** — Menganalisis kondisi siswa dan menyusun strategi adaptasi materi
2. **Adaptive Agent** — Menulis ulang dan menyederhanakan materi sesuai strategi profiling
3. **Insight Agent** — Mengaudit inklusivitas materi dan memberikan Readability Score (0–100)

Output akhir berupa **PDF RPP Inklusif** yang siap digunakan guru di kelas.

---

## Arsitektur Sistem

```
Input Guru (data siswa + materi)
        │
        ▼
┌─────────────────────────────────────┐
│         CrewAI Pipeline             │
│  Agent 1: Profiling                 │
│     └── cari_pedoman (RAG)          │◄── ChromaDB (WCAG, Permendikbud)
│  Agent 2: Adaptive                  │
│     └── cari_pedoman (RAG)          │
│  Agent 3: Insight                   │
└──────────────┬──────────────────────┘
               │
               ▼
    ┌──────────────────────┐
    │  Generate Output     │
    │  - PDF RPP Inklusif  │
    │  - 3 file Markdown   │
    └──────────────────────┘
```

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| **AI Orchestration** | CrewAI |
| **LLM** | Groq API · `openai/gpt-oss-120b` |
| **Embedding Model** | HuggingFace · `intfloat/multilingual-e5-base` |
| **Vector Database** | ChromaDB |
| **Relational Database** | PostgreSQL (Amazon RDS) |
| **Cache** | Redis (Amazon ElastiCache) |
| **PDF Generator** | ReportLab |
| **Cloud** | Amazon EC2 · RDS · ElastiCache · S3 |
| **Integrasi** | LangChain (wrapper embedding + ChromaDB) |

---

## Struktur Folder

```
SetupVectorDatabase/
├── config/
│   ├── agents.yaml          # Konfigurasi persona tiap agent
│   └── tasks.yaml           # Konfigurasi tugas tiap agent
├── knowledge/               # Folder PDF pedoman inklusif (WCAG, Permendikbud) — tidak di-push
├── input/                   # Folder dokumen materi guru (.docx / .pdf) — tidak di-push
├── output/                  # Hasil generate RPP — tidak di-push
├── database/                # Data ChromaDB lokal — tidak di-push
├── crew.py                  # Definisi agent, tools, dan crew pipeline
├── main.py                  # Entry point utama & PDF generator
├── db_connection.py         # Koneksi PostgreSQL & Redis
├── ingest_pedoman.py        # Ingest PDF pedoman ke ChromaDB + PostgreSQL
├── init_chroma.py           # Inisialisasi ChromaDB dengan data referensi awal
├── test_pdf.py              # Test generate PDF tanpa menjalankan AI
├── requirements.txt
└── .env.example
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

Buka `.env` dan isi:

```env
# Groq API
GROQ_API_KEY=your_groq_api_key_here

# PostgreSQL (Amazon RDS)
DB_HOST=your-rds-endpoint.rds.amazonaws.com
DB_NAME=asiq_db
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_PORT=5432

# Redis (Amazon ElastiCache)
REDIS_HOST=your-elasticache-endpoint
REDIS_PORT=6379
```

> **Catatan:** PostgreSQL dan Redis hanya dapat diakses dari EC2 dalam VPC yang sama. Sistem tetap berjalan tanpa keduanya (graceful fallback).

### 5. Siapkan Folder

```bash
mkdir knowledge input
```

- Masukkan file PDF pedoman inklusif (WCAG, Permendikbud, dll.) ke folder `knowledge/`
- Masukkan dokumen materi guru (`.docx` / `.pdf`) ke folder `input/`

### 6. Inisialisasi Vector Database

Jalankan salah satu (pilih sesuai kebutuhan):

```bash
# Opsi A — Inisialisasi dengan data referensi awal (cepat, untuk testing)
python init_chroma.py

# Opsi B — Ingest PDF pedoman dari folder knowledge/ (lengkap, untuk production)
python ingest_pedoman.py
```

---

## Menjalankan Sistem

### Mode Normal (Input dari Guru)

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

Lalu jalankan:
```bash
python main.py
```

Sistem otomatis menggunakan data dummy dan dokumen pertama dari `input/` (jika ada).

### Test PDF Tanpa AI

Untuk mengecek layout PDF tanpa menjalankan pipeline AI:

```bash
python test_pdf.py
```

---

## Output

Setiap run menghasilkan folder `output/YYYYMMDD_HHMMSS_NamaSiswa/` berisi:

| File | Isi |
|---|---|
| `01_Strategi_Profiling.md` | Strategi adaptasi dari Agent 1 |
| `02_Materi_Adaptif.md` | Materi yang sudah diadaptasi dari Agent 2 |
| `03_Laporan_Audit.md` | Laporan audit inklusivitas dari Agent 3 |
| `RPP_Inklusif_NamaSiswa_timestamp.pdf` | PDF RPP siap pakai |

---

## Catatan Teknis

- **GPU (CUDA) diperlukan** untuk menjalankan embedding model `intfloat/multilingual-e5-base` secara lokal
- **Groq API** memiliki rate limit — sistem sudah dilengkapi delay otomatis (60 detik antar task, 30 detik antar step)
- **Database cloud** (RDS & Redis) hanya aktif saat sistem berjalan di EC2 dalam VPC AWS; di lokal akan di-skip otomatis

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
