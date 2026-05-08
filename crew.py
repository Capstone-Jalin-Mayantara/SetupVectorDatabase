import os
import time
from dotenv import load_dotenv
from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from db_connection import REDIS_ENABLED, redis_client

load_dotenv(override=True)

MODEL_NAME = "intfloat/multilingual-e5-base"
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "chroma_db")
CACHE_TTL = 3600  # 1 jam

local_llm = LLM(
    model="groq/openai/gpt-oss-120b",
    api_key=os.environ.get("GROQ_API_KEY"),
)

# Load ChromaDB dengan prefix "query:" — dipakai saat agent mencari pedoman
_embeddings_query = HuggingFaceEmbeddings(
    model_name=MODEL_NAME,
    model_kwargs={"device": "cuda"},
    encode_kwargs={
        "normalize_embeddings": True,
        "prompt": "query: "
    }
)
_vectorstore = Chroma(
    persist_directory=DB_DIR,
    embedding_function=_embeddings_query
)


# ── TOOLS ────────────────────────────────────────────────────────────────────

@tool("cari_pedoman")
def cari_pedoman(query: str) -> str:
    """Cari informasi relevan dari database pedoman inklusif (WCAG, Permendikbud, standar inklusi)
    berdasarkan query teks. Gunakan tool ini sebelum membuat keputusan tentang kebutuhan siswa,
    strategi adaptasi materi, atau penilaian aksesibilitas."""
    if isinstance(query, dict):
        query = query.get("description") or query.get("query") or str(query)
    hasil = _vectorstore.similarity_search(query, k=1)
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
        return Agent(
            config=self.agents_config['profiling_agent'],
            llm=local_llm,
            tools=[cari_pedoman],
            verbose=True
        )

    @agent
    def adaptive_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['adaptive_agent'],
            llm=local_llm,
            tools=[cari_pedoman],
            verbose=True
        )

    @agent
    def insight_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['insight_agent'],
            llm=local_llm,
            tools=[],
            verbose=True
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
            task_callback=lambda _: time.sleep(60),
            step_callback=lambda _: time.sleep(30),
        )
