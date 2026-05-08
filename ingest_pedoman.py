import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from db_connection import get_postgres_connection

load_dotenv()

MODEL_NAME = "intfloat/multilingual-e5-base"
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "chroma_db")


def _simpan_ke_postgres(chunks):
    """Simpan metadata setiap chunk ke tabel document_chunks di RDS PostgreSQL."""
    print("🗄️ Menyimpan metadata chunks ke RDS PostgreSQL...")
    conn = get_postgres_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id          SERIAL PRIMARY KEY,
            source      TEXT,
            content     TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for chunk in chunks:
        cursor.execute(
            "INSERT INTO document_chunks (source, content) VALUES (%s, %s)",
            (chunk.metadata.get("source", "unknown"), chunk.page_content)
        )

    conn.commit()
    cursor.close()
    conn.close()
    print(f"✅ {len(chunks)} chunks berhasil disimpan ke PostgreSQL (tabel: document_chunks).")


def ingest_documents():
    print("🔍 Memulai proses pembacaan dokumen pedoman dari folder 'knowledge'...")

    knowledge_dir = "./knowledge"
    if not os.path.exists(knowledge_dir):
        print(f"❌ Folder '{knowledge_dir}' tidak ditemukan. Silakan buat dan masukkan file PDF Anda.")
        return

    print("📄 Mengekstrak teks dari file PDF...")
    pdf_loader = PyPDFDirectoryLoader(knowledge_dir)
    documents = pdf_loader.load()

    if not documents:
        print("⚠️ Tidak ada file PDF yang ditemukan di dalam folder 'knowledge'.")
        return

    print(f"✅ Berhasil membaca {len(documents)} halaman dokumen.")

    print("✂️ Memotong teks menjadi bagian-bagian kecil (chunking)...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = text_splitter.split_documents(documents)
    print(f"✅ Dokumen berhasil dipotong menjadi {len(chunks)} bagian (chunks).")

    # Prefix "passage: " wajib untuk model multilingual-e5 saat indexing dokumen
    print(f"🤗 Menyiapkan HuggingFace Embeddings ({MODEL_NAME}) di CUDA...")
    embeddings = HuggingFaceEmbeddings(
        model_name=MODEL_NAME,
        model_kwargs={"device": "cuda"},
        encode_kwargs={
            "normalize_embeddings": True,
            "prompt": "passage: "
        }
    )

    os.makedirs(DB_DIR, exist_ok=True)
    print(f"💾 Menyimpan data ke Vector Database ChromaDB di {DB_DIR}...")
    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=DB_DIR
    )
    print("✅ ChromaDB berhasil diperbarui.")

    # Simpan metadata ke PostgreSQL (hanya berjalan jika RDS dapat diakses)
    try:
        _simpan_ke_postgres(chunks)
        print("🎉 SUKSES! Semua pedoman inklusif telah tersimpan di ChromaDB dan PostgreSQL.")
    except Exception as e:
        print(f"⚠️ PostgreSQL tidak dapat diakses ({type(e).__name__}). ChromaDB tetap tersimpan.")
        print("   Metadata ke RDS akan tersinkron saat sistem berjalan di EC2.")


if __name__ == "__main__":
    ingest_documents()
