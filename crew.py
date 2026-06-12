import os
import re
import time
import logging
from dotenv import load_dotenv
from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from db_connection import REDIS_ENABLED, redis_client

load_dotenv(override=True)

log = logging.getLogger("asiq.crew")

MODEL_NAME = "intfloat/multilingual-e5-base"
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "chroma_db")
CACHE_TTL = 3600  # 1 jam

# Provider LLM: OpenRouter (berbayar, tanpa limit TPM/TPD ketat) jika key tersedia,
# fallback ke Groq free tier (TPM 8k, TPD 500k).
_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Delay antar task/step — hanya perlu untuk Groq free tier yang gampang throttle.
# OpenRouter pay-as-you-go tidak butuh delay.
_default_task_delay = "0" if _OPENROUTER_KEY else "30"
_default_step_delay = "0" if _OPENROUTER_KEY else "8"
_TASK_DELAY  = int(os.getenv("GROQ_TASK_DELAY",  _default_task_delay))
_STEP_DELAY  = int(os.getenv("GROQ_STEP_DELAY",  _default_step_delay))
_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "3"))    # retry jika rate-limited

# Batas panjang materi yang dikirim ke LLM. Free tier Groq: TPM 8.000 token —
# dokumen 72k karakter ≈ 19k token langsung ditolak (413). 12k char ≈ 3-4k token.
_MATERI_MAX_CHARS = int(os.getenv("MATERI_MAX_CHARS", "12000"))

if _OPENROUTER_KEY:
    local_llm = LLM(
        model="openrouter/openai/gpt-oss-120b",
        api_key=_OPENROUTER_KEY,
    )
    log.info("LLM provider: OpenRouter (gpt-oss-120b)")
else:
    local_llm = LLM(
        model="groq/openai/gpt-oss-120b",
        api_key=os.environ.get("GROQ_API_KEY"),
    )
    log.info("LLM provider: Groq free tier (gpt-oss-120b)")

# Singleton embedding model — di-load sekali saat modul pertama kali diimport.
# Hindari reload berulang yang memakan waktu 15-30 detik per request.
_embeddings_query: HuggingFaceEmbeddings | None = None
_vectorstore: Chroma | None = None


def _get_vectorstore() -> Chroma:
    global _embeddings_query, _vectorstore
    if _vectorstore is None:
        device = "cuda" if _cuda_available() else "cpu"
        log.info("Memuat embedding model '%s' di device '%s'...", MODEL_NAME, device)
        _embeddings_query = HuggingFaceEmbeddings(
            model_name=MODEL_NAME,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True, "prompt": "query: "},
        )
        _vectorstore = Chroma(
            persist_directory=DB_DIR,
            embedding_function=_embeddings_query,
        )
        log.info("Vectorstore ChromaDB siap.")
    return _vectorstore


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _task_callback(_task_output):
    """Delay antar task untuk menghindari throttle Groq API."""
    if _TASK_DELAY > 0:
        log.debug("Task selesai — tunggu %ds sebelum task berikutnya.", _TASK_DELAY)
        time.sleep(_TASK_DELAY)


def _step_callback(_step_output):
    """Delay antar step di dalam satu task."""
    if _STEP_DELAY > 0:
        time.sleep(_STEP_DELAY)


# ── TOOLS ────────────────────────────────────────────────────────────────────

@tool("cari_pedoman")
def cari_pedoman(query: str) -> str:
    """Cari informasi relevan dari database pedoman inklusif (WCAG, Permendikbud, standar inklusi)
    berdasarkan query teks. Gunakan tool ini sebelum membuat keputusan tentang kebutuhan siswa,
    strategi adaptasi materi, atau penilaian aksesibilitas."""
    if isinstance(query, dict):
        query = query.get("description") or query.get("query") or str(query)
    hasil = _get_vectorstore().similarity_search(query, k=1)
    if not hasil:
        return "Tidak ditemukan dokumen relevan untuk query ini."
    return "\n\n---\n\n".join(
        [f"[Sumber: {doc.metadata.get('sumber', 'N/A')}]\n{doc.page_content}" for doc in hasil]
    )


@tool("cek_cache_profiling")
def cek_cache_profiling(kunci_diagnosis: str) -> str:
    """Cek apakah strategi profiling untuk diagnosis tertentu sudah tersimpan di Redis cache.
    Panggil tool ini PERTAMA KALI sebelum query ChromaDB. Jika hasilnya '[DARI CACHE]',
    gunakan langsung tanpa perlu query lagi.
    Input: nama diagnosis siswa, contoh: 'Disleksia', 'ADHD', 'Autisme', 'Slow Learner'."""
    if not REDIS_ENABLED:
        return "Cache tidak tersedia (REDIS_ENABLED=False). Lanjutkan dengan query ChromaDB."
    cached = redis_client.get(f"profiling:{kunci_diagnosis.lower()}")
    if cached:
        return f"[DARI CACHE] Strategi profiling untuk '{kunci_diagnosis}' ditemukan:\n\n{cached}"
    return f"Cache kosong untuk '{kunci_diagnosis}'. Lanjutkan dengan query ChromaDB menggunakan tool cari_pedoman."


@tool("simpan_cache_profiling")
def simpan_cache_profiling(kunci_diagnosis: str, strategi: str) -> str:
    """Simpan strategi profiling ke Redis cache setelah selesai membuatnya.
    Panggil tool ini di AKHIR setelah strategi profiling selesai dibuat.
    Input kunci_diagnosis: nama diagnosis (contoh: 'Disleksia').
    Input strategi: isi lengkap strategi adaptasi yang baru dibuat."""
    if not REDIS_ENABLED:
        return "Cache tidak tersedia (REDIS_ENABLED=False). Strategi tidak disimpan, tetap lanjutkan."
    redis_client.setex(
        f"profiling:{kunci_diagnosis.lower()}",
        CACHE_TTL,
        strategi
    )
    return f"✅ Strategi untuk '{kunci_diagnosis}' disimpan ke cache (berlaku {CACHE_TTL // 3600} jam)."


# ── CREW ─────────────────────────────────────────────────────────────────────

@CrewBase
class AsiqAgents():
    """Kumpulan Agent ASIQ"""
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def profiling_agent(self) -> Agent:
        # cek_cache_profiling dipanggil PERTAMA — jika cache hit, tidak perlu panggil LLM lagi.
        # simpan_cache_profiling dipanggil di AKHIR untuk menyimpan strategi baru ke Redis.
        # Saat Redis down, tool cache tidak diberikan — mengurangi tool call sia-sia
        # yang memicu error "tool_use_failed" di model gpt-oss Groq.
        _tools = ([cek_cache_profiling, cari_pedoman, simpan_cache_profiling]
                  if REDIS_ENABLED else [cari_pedoman])
        return Agent(
            config=self.agents_config['profiling_agent'],
            llm=local_llm,
            tools=_tools,
            verbose=True,
        )

    @agent
    def adaptive_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['adaptive_agent'],
            llm=local_llm,
            tools=[cari_pedoman],
            verbose=True,
        )

    @agent
    def insight_agent(self) -> Agent:
        # Insight agent hanya evaluasi — tidak butuh tool agar tidak looping.
        return Agent(
            config=self.agents_config['insight_agent'],
            llm=local_llm,
            tools=[],
            verbose=True,
        )

    @task
    def profiling_task(self) -> Task:
        return Task(config=self.tasks_config['profiling_task'])

    @task
    def adaptive_task(self) -> Task:
        return Task(config=self.tasks_config['adaptive_task'])

    @task
    def insight_task(self) -> Task:
        return Task(config=self.tasks_config['insight_task'])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            task_callback=_task_callback,
            step_callback=_step_callback,
        )


def _pangkas_materi(teks: str) -> str:
    """Pangkas dokumen materi agar muat di limit token Groq.

    Dokumen guru sering berisi beberapa modul ajar sekaligus (struktur A-R
    berulang) plus boilerplate yang tidak berguna untuk adaptasi. Tiga lapis:
    1. Ambil modul pertama saja jika 'MODUL AJAR' muncul lebih dari sekali.
    2. Buang bagian Daftar Pustaka/Glosarium/Bahan Bacaan/LKPD/tanda tangan.
    3. Potong keras di batas paragraf maksimal _MATERI_MAX_CHARS."""
    if not teks:
        return teks

    # 1. Modul berulang → modul pertama saja
    matches = list(re.finditer(r"MODUL\s+AJAR", teks, re.IGNORECASE))
    if len(matches) > 1:
        teks = teks[:matches[1].start()]

    # 2. Buang section boilerplate (dari headingnya sampai heading huruf berikutnya)
    teks = re.sub(
        r"(?ms)^\s*[A-Z]\.\s*(Bahan Bacaan|Glosarium|Daftar Pustaka|LKPD)\b.*?(?=^\s*[A-Z]\.\s|\Z)",
        "", teks)
    # Blok tanda tangan: "Mengetahui ... NIP. xxxx"
    teks = re.sub(r"(?ms)^\s*Mengetahui\b.*?NIP\.?\s*[\d ]+\s*$", "", teks)

    # 3. Potong di batas paragraf
    teks = teks.strip()
    if len(teks) > _MATERI_MAX_CHARS:
        potong = teks.rfind("\n\n", 0, _MATERI_MAX_CHARS)
        if potong < _MATERI_MAX_CHARS // 2:
            potong = _MATERI_MAX_CHARS
        teks = teks[:potong].rstrip() + "\n\n[Materi dipangkas otomatis agar muat dalam batas token]"
    return teks


def _cek_output_rusak(hasil) -> str:
    """Return nama task pertama yang output-nya tidak valid, atau '' jika semua OK.

    Output dianggap rusak jika terlalu pendek — gejala model menjawab
    'We will call the tool.' dkk. sebagai final answer tanpa konten."""
    try:
        outputs = hasil.tasks_output
    except Exception:
        return ""
    for t in outputs:
        raw = (getattr(t, "raw", "") or "").strip()
        if len(raw) < 300:
            return getattr(t, "name", None) or getattr(t, "description", "")[:40] or "?"
    return ""


def run_crew_with_retry(inputs: dict) -> object:
    """Jalankan crew dengan retry otomatis.
    Menangani: rate limit Groq (429) dan error intermiten 'tool_use_failed'
    (model gpt-oss kadang mengeluarkan tool call saat tool_choice=none)."""
    import random

    if inputs.get("materi_mentah"):
        asli = len(inputs["materi_mentah"])
        inputs = {**inputs, "materi_mentah": _pangkas_materi(inputs["materi_mentah"])}
        if len(inputs["materi_mentah"]) < asli:
            log.info("Materi dipangkas: %d → %d karakter (limit token Groq).",
                     asli, len(inputs["materi_mentah"]))

    last_exc = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            hasil = AsiqAgents().crew().kickoff(inputs=inputs)
            rusak = _cek_output_rusak(hasil)
            if rusak:
                # Model kadang menjawab "We will call the tool." sebagai final answer
                # (gagal format ReAct) — hasilnya sampah pendek. Ulangi pipeline.
                log.warning("Output task '%s' tidak valid (attempt %d/%d) — pipeline diulang...",
                            rusak, attempt, _MAX_RETRIES)
                last_exc = RuntimeError(f"Output task '{rusak}' tidak valid/terlalu pendek")
                time.sleep(2)
                continue
            return hasil
        except Exception as exc:
            msg = str(exc).lower()
            if "rate limit" in msg or "429" in msg or "too many" in msg:
                wait = (2 ** attempt) + random.uniform(0, 2)
                log.warning("Rate limit hit (attempt %d/%d). Retry dalam %.1fs...", attempt, _MAX_RETRIES, wait)
                time.sleep(wait)
                last_exc = exc
            elif "tool_use_failed" in msg or "tool choice is none" in msg:
                wait = 3 + random.uniform(0, 2)
                log.warning("Groq tool_use_failed (attempt %d/%d) — error intermiten, retry dalam %.1fs...",
                            attempt, _MAX_RETRIES, wait)
                time.sleep(wait)
                last_exc = exc
            else:
                raise
    raise RuntimeError(f"Pipeline gagal setelah {_MAX_RETRIES} retry: {last_exc}") from last_exc
