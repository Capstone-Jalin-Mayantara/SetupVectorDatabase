import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

# 1. Load API Key dari file .env
load_dotenv()

def ingest_documents():
    print("🔍 Memulai proses pembacaan dokumen pedoman dari folder 'knowledge'...")
    
    knowledge_dir = "./knowledge"
    
    # Cek apakah folder knowledge ada
    if not os.path.exists(knowledge_dir):
        print(f"❌ Folder '{knowledge_dir}' tidak ditemukan. Silakan buat dan masukkan file PDF Anda.")
        return

    # 2. Membaca SEMUA file PDF di dalam folder secara otomatis
    print("📄 Mengekstrak teks dari file PDF...")
    pdf_loader = PyPDFDirectoryLoader(knowledge_dir)
    documents = pdf_loader.load()
    
    if not documents:
        print("⚠️ Tidak ada file PDF yang ditemukan di dalam folder 'knowledge'.")
        return
        
    print(f"✅ Berhasil membaca {len(documents)} halaman dokumen.")

    # 3. Memotong dokumen menjadi bagian-bagian kecil (Chunking)
    # Ini wajib agar AI tidak kebingungan membaca teks yang terlalu panjang sekaligus
    print("✂️ Memotong teks menjadi bagian-bagian kecil (chunking)...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, 
        chunk_overlap=200
    )
    chunks = text_splitter.split_documents(documents)
    print(f"✅ Dokumen berhasil dipotong menjadi {len(chunks)} bagian (chunks).")

    # 4. Menyiapkan Model Embeddings (Generasi terbaru sesuai perbaikan sebelumnya)
    print("🧠 Menyiapkan Google Gemini Embeddings (text-embedding-004)...")
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")

    # 5. Memasukkan dan Menyimpan ke ChromaDB
    db_dir = "./database/chroma_db"
    print(f"💾 Menyimpan data ke Vector Database ChromaDB di {db_dir}...")
    
    # Proses ini mungkin memakan waktu 1-3 menit tergantung jumlah halaman PDF
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=db_dir
    )
    
    print("🎉 SUKSES BESAR! Semua pedoman WCAG dan Inklusif telah tertanam di otak AI Anda.")

if __name__ == "__main__":
    ingest_documents()