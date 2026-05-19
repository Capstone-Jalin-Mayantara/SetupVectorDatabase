import os
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

# Delay antar task/step — turunkan jika Groq plan sudah tier berbayar
_TASK_DELAY  = int(os.getenv("GROQ_TASK_DELAY",  "30"))   # detik antar task (default 30, was 60)
_STEP_DELAY  = int(os.getenv("GROQ_STEP_DELAY",  "8"))    # detik antar step (default 8, was 30)
_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "3"))    # retry jika rate-limited

local_llm = LLM(
    model="groq/openai/gpt-oss-120b",
    api_key=os.environ.get("GROQ_API_KEY"),
)

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
        return Agent(
            config=self.agents_config['profiling_agent'],
            llm=local_llm,
            tools=[cek_cache_profiling, cari_pedoman, simpan_cache_profiling],
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


def run_crew_with_retry(inputs: dict) -> object:
    """Jalankan crew dengan exponential backoff jika Groq rate-limit (429)."""
    import random
    last_exc = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return AsiqAgents().crew().kickoff(inputs=inputs)
        except Exception as exc:
            msg = str(exc).lower()
            if "rate limit" in msg or "429" in msg or "too many" in msg:
                wait = (2 ** attempt) + random.uniform(0, 2)
                log.warning("Rate limit hit (attempt %d/%d). Retry dalam %.1fs...", attempt, _MAX_RETRIES, wait)
                time.sleep(wait)
                last_exc = exc
            else:
                raise
    raise RuntimeError(f"Pipeline gagal setelah {_MAX_RETRIES} retry: {last_exc}") from last_exc
