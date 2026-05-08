import os
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

MODEL_NAME = "intfloat/multilingual-e5-base"
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "chroma_db")

# 1. INISIALISASI EMBEDDING (prefix "passage:" wajib untuk model e5 saat indexing)
print(f"⏳ Menyiapkan HuggingFace Embeddings ({MODEL_NAME}) di CUDA...")
embeddings_index = HuggingFaceEmbeddings(
    model_name=MODEL_NAME,
    model_kwargs={"device": "cuda"},
    encode_kwargs={
        "normalize_embeddings": True,
        "prompt": "passage: "
    }
)

# 2. SIAPKAN DOKUMEN REFERENSI (KNOWLEDGE BASE)
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

# 3. BUAT DAN SIMPAN KE CHROMADB
os.makedirs(DB_DIR, exist_ok=True)
print(f"📁 Menyimpan dokumen ke Vector Database di: {DB_DIR}")
Chroma.from_documents(
    documents=dokumen_referensi,
    embedding=embeddings_index,
    persist_directory=DB_DIR
)

# 4. TES RETRIEVAL — gunakan prefix "query:" saat mencari (berbeda dari "passage:")
print("\n🔍 --- Tes Retrieval (RAG) ---")
embeddings_query = HuggingFaceEmbeddings(
    model_name=MODEL_NAME,
    model_kwargs={"device": "cuda"},
    encode_kwargs={
        "normalize_embeddings": True,
        "prompt": "query: "
    }
)
vectorstore_query = Chroma(
    persist_directory=DB_DIR,
    embedding_function=embeddings_query
)

query = "Bagaimana aturan menulis teks untuk siswa disleksia?"
hasil_pencarian = vectorstore_query.similarity_search(query, k=1)

print(f"Pertanyaan: {query}")
print(f"Hasil dari Database: {hasil_pencarian[0].page_content}")
print("\n✅ Task 1.3 Setup Vector Database BERHASIL!")
