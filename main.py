from dotenv import load_dotenv
import os

# Load environment variables (.env)
load_dotenv()

from agents.learner_agent import learner_profiling
from agents.adaptive_agent import adaptive_transformation
from agents.insight_agent import inclusivity_insight


def run():
    print("🚀 Sistem mulai berjalan...\n")

    # Input dummy (bisa kamu ganti nanti)
    input_data = "Siswa kelas 3 SD, kesulitan membaca teks panjang dan lebih mudah memahami dengan gambar"
    materi = "Fotosintesis adalah proses di mana tumbuhan hijau membuat makanan sendiri dengan bantuan cahaya matahari, air, dan karbon dioksida..."

    try:
        # Step 1: Profiling
        print("🔍 Analisis profil siswa...")
        profil = learner_profiling(input_data)
        print("✅ Profil selesai\n")

        # Step 2: Adaptasi Materi
        print("🔄 Adaptasi materi...")
        adaptasi = adaptive_transformation(materi, profil)
        print("✅ Adaptasi selesai\n")

        # Step 3: Evaluasi
        print("📊 Evaluasi inklusivitas...")
        evaluasi = inclusivity_insight(adaptasi)
        print("✅ Evaluasi selesai\n")

        # Output
        print("\n=== HASIL AKHIR ===")
        print("\n📘 Materi Adaptasi:\n", adaptasi)
        print("\n📈 Evaluasi:\n", evaluasi)

    except Exception as e:
        print("❌ Terjadi error:")
        print(e)


if __name__ == "__main__":
    run()