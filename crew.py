from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from langchain_google_genai import ChatGoogleGenerativeAI

# === INILAH KODE YANG MENYAMBUNGKAN KE API GEMINI ===
# Program otomatis mengambil kunci dari file .env yang kamu buat tadi
gemini_llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.3)

@CrewBase
class AsiqAgents():
    """Kumpulan Agent ASIQ"""
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def profiling_agent(self) -> Agent:
        # Perhatikan: kita memasukkan "gemini_llm" sebagai otak agen ini
        return Agent(config=self.agents_config['profiling_agent'], llm=gemini_llm, verbose=True)

    @agent
    def adaptive_agent(self) -> Agent:
        return Agent(config=self.agents_config['adaptive_agent'], llm=gemini_llm, verbose=True)

    @agent
    def insight_agent(self) -> Agent:
        return Agent(config=self.agents_config['insight_agent'], llm=gemini_llm, verbose=True)

    @task
    def profiling_task(self) -> Task:
        return Task(config=self.tasks_config['profiling_task'])

    @task
    def adaptive_task(self) -> Task:
        return Task(config=self.tasks_config['adaptive_task'])

    @task
    def insight_task(self) -> Task:
        return Task(config=self.tasks_config['insight_task'], output_file='Laporan_Akhir_ASIQ.md')

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential, # Tugas estafet
            verbose=True,
        )