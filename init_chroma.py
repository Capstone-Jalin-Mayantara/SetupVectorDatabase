import os
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document

# 1. LOAD DAN VALIDASI API KEY
# Ini akan mencegah error jika file .env belum terbaca
load_dotenv()
if not os.environ.get("GOOGLE_API_KEY"):
    raise ValueError("🚨 ERROR: GOOGLE_API_KEY tidak ditemukan! Pastikan file .env sudah di-save dan formatnya benar.")

# 2. INISIALISASI EMBEDDING GEMINI
# Kita menggunakan penulisan model terbaru tanpa awalan "models/"
print("⏳ Menyiapkan Gemini Embeddings...")
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

# 3. SIAPKAN DOKUMEN REFERENSI (KNOWLEDGE BASE)
dokumen_referensi = [
    Document(
        page_content="Panduan Aksesibilitas WCAG: Teks untuk siswa Disleksia harus menggunakan kalimat pendek, maksimal 10-15 kata per kalimat. Hindari penggunaan kata majemuk yang rumit. Gunakan poin-poin (bullet points) untuk instruksi.",
        metadata={"sumber": "Standar WCAG 2.1", "topik": "Disleksia"}
    ),
    Document(
        page_content="Regulasi Permendikbud: Modul ajar untuk anak lamban belajar (slow learner) harus menghindari istilah teknis/ilmiah kecuali disertai definisi langsung yang sangat sederhana.",
        metadata={"sumber": "Permendikbud Inklusif", "topik": "Slow Learner"}
    )
]

# 4. BUAT DAN SIMPAN KE CHROMADB LOKAL
# Pastikan folder database dibuat di tempat yang benar
lokasi_db = os.path.join(os.path.dirname(__file__), "database", "chroma_db")
os.makedirs(lokasi_db, exist_ok=True)

print(f"📁 Menyimpan dokumen ke Vector Database di: {lokasi_db}")
vectorstore = Chroma.from_documents(
    documents=dokumen_referensi,
    embedding=embeddings,
    persist_directory=lokasi_db
)

# 5. TES PENCARIAN (RETRIEVAL)
print("\n🔍 --- Tes Retrieval (RAG) ---")
query = "Bagaimana aturan menulis teks untuk siswa disleksia?"
hasil_pencarian = vectorstore.similarity_search(query, k=1)

print(f"Pertanyaan: {query}")
print(f"Hasil dari Database: {hasil_pencarian[0].page_content}")
print("\n✅ Task 1.3 Setup Vector Database BERHASIL!")