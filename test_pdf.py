"""
Test generate PDF — jalankan tanpa crew/AI.
Pakai data dummy untuk cek layout dan format PDF.

Jalankan:
    python test_pdf.py
"""

from main import generate_pdf, _create_output_dir, _save_markdown_files

# ── Data siswa dummy ──────────────────────────────────────────────────────────
data = {
    "nama_siswa":     "Budi Santoso",
    "kelas":          "2 SD",
    "mata_pelajaran": "Bahasa Indonesia",
    "gejala": (
        "susah fokus, tidak bisa diam, sering menggerakkan tangan dan kaki, "
        "sulit duduk lama, mudah terdistraksi oleh suara sekitar"
    ),
}

# ── Output dummy Agent 1 — Profiling ─────────────────────────────────────────
profiling_out = """
Berdasarkan kondisi siswa Budi Santoso (Kelas 2 SD) dengan gejala ADHD, berikut strategi adaptasi materi:

**Aturan Penulisan Teks:**
- Maksimal 8 kata per kalimat
- Gunakan kalimat aktif dan sederhana
- Hindari kata abstrak atau istilah ilmiah

**Panjang Paragraf:**
- Maksimal 2-3 kalimat per paragraf
- Beri jeda visual antar paragraf (baris kosong)

**Instruksi Visual:**
- Gunakan poin-poin (bullet points) untuk semua instruksi
- Sertakan ikon atau gambar pendukung di setiap bagian
- Gunakan teks tebal untuk kata kunci

**Aktivitas:**
- Pecah setiap sesi belajar menjadi 5-10 menit
- Sertakan aktivitas gerak fisik ringan setiap 10 menit
- Berikan instruksi satu per satu, tidak sekaligus
"""

# ── Output Agent 2 — Materi Adaptif (output nyata dari AI) ───────────────────
adaptive_out = """
### Modul Pembelajaran Menulis Teks Sederhana untuk Kelas 2 SD

**Tujuan Pembelajaran:**
- Memahami dasar-dasar menulis teks sederhana.
- Mengembangkan keterampilan menulis huruf dan kata.
- Menulis kalimat rumpang dengan benar.

---

#### **Bagian 1: Latihan Tulisan Tanganku**

**Petunjuk:** Tulislah kalimat di bawah ini dengan rapi dan benar. Perhatikan huruf kapital, jarak antar kata, dan titik di akhir kalimat.

1. Ini hari yang cerah.
2. Saya pergi ke sekolah.
3. Saya suka belajar Bahasa Indonesia.

**Gambar 1:** Ilustrasi Tulisan Rapi

---

#### **Bagian 2: Cerita tentang Diriku dan Keluargaku**

**Petunjuk:** Lengkapi kalimat rumpang di bawah ini dengan jawabanmu sendiri. Kemudian, gambarlah tentang ceritamu.

- Nama saya adalah [__].
- Saya suka bermain [__].
- Di rumah, saya punya [__].
- Ayah saya bekerja sebagai [__].
- Ibu saya suka [__].

**Gambar 2:** Ilustrasi Cerita

---

#### **Bagian 3: Menulis Kalimat Rumpang**

1. Saya [__] di sekolah.
2. Setiap minggu, saya menghadiri [__].
3. Di rumah, saya sering membantu [__].

**Checklist:**
- Sudah menuliskan kalimat rumpang dengan benar?
- Sudah memasukkan tanda baca yang tepat?

---

#### **Bagian 4: Menulis Kalimat Lengkap**

1. Saya suka bermain sepak bola.
2. Setiap minggu, saya menghadiri pertandingan sepak bola di sekolah.
3. Di rumah, saya sering membantu ibu membersihkan rumah.

**Checklist:**
- Sudah menuliskan kalimat dengan benar?
- Jarak antar kata sudah pas?

---

#### **Bagian 5: Presentasi dan Diskusi**

Presentasikan cerita yang telah kalian buat kepada teman sekelas. Gunakan gambar untuk membantu menjelaskan.

**Checklist:**
- Sudah siapkan presentasi?
- Gambar sudah ditaruh dengan benar?

---

#### **Bagian 6: Pengayaan dan Remedial**

1. **Pengayaan:** Menulis cerita pendek atau puisi.
2. **Remedial:** Latihan menulis huruf dan kata.

**Checklist:**
- Sudah berlatih menulis dengan lebih baik?
- Masih ada kesulitan dalam menulis?

---

### Lembar Kerja Peserta Didik (LKPD)

**Nama:** ________________________
**Kelas:** ________________________
**Tanggal:** ________________________

#### **Latihan Tulisan Tanganku**

Tulislah kalimat di bawah ini dengan rapi dan benar. Perhatikan huruf kapital, jarak antar kata, dan titik di akhir kalimat.

1. ___________________________________________________
2. ___________________________________________________
3. ___________________________________________________

**Gambar 3:** Gambar Kalimat

---

#### **Cerita tentang Diriku dan Keluargaku**

- Nama saya adalah [__].
- Saya suka bermain [__].
- Di rumah, saya punya [__].
- Ayah saya bekerja sebagai [__].
- Ibu saya suka [__].

**Gambar 4:** Gambar Cerita

---

#### **Menulis Kalimat Lengkap**

1. Saya [__] di sekolah.
2. Setiap minggu, saya menghadiri [__].
3. Di rumah, saya sering membantu [__].

---

### Rubrik Penilaian Analitik untuk Tugas Diskusi Kelompok

- Sudah menuliskan kalimat rumpang dengan benar?
- Sudah memasukkan tanda baca yang tepat?

---

Terima kasih telah berpartisipasi dalam modul ini. Semoga kalian dapat mengembangkan kemampuan menulis teks sederhana dengan lebih baik!

---

Teks ini sudah disederhanakan, terstruktur rapi, dan siap diberikan langsung kepada siswa. Penggunaan checklist visual dan ilustrasi memastikan bahwa materi menjadi mudah dipahami dan dikembangkan.
"""

# ── Output dummy Agent 3 — Laporan Audit ─────────────────────────────────────
insight_out = """
**Laporan Audit Inklusivitas — Materi Huruf Vokal dan Konsonan**

**Readability Score: 87 / 100**

---

**Kelebihan Materi:**
- Kalimat sangat pendek, rata-rata 5-6 kata per kalimat
- Penggunaan bullet points konsisten dan membantu navigasi
- Kata-kata sederhana dan sesuai usia kelas 2 SD
- Pemisahan visual antar bagian sudah baik

**Area yang Sudah Memenuhi Standar WCAG:**
- Struktur hierarki teks jelas (judul, subjudul, isi)
- Tidak ada istilah teknis tanpa penjelasan
- Instruksi diberikan satu per satu

**Rekomendasi Perbaikan:**
- Tambahkan gambar ilustrasi untuk setiap huruf vokal
- Pertimbangkan font sans-serif ukuran 14pt untuk cetak
- Tambahkan reward/pujian setelah setiap latihan selesai

**Kesimpulan:**
Materi sudah sangat layak digunakan untuk siswa dengan ADHD.
Skor inklusivitas 87/100 menunjukkan kualitas yang baik.
"""

# ── Generate PDF ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[*] Generating PDF test...")
    output_dir = _create_output_dir(data["nama_siswa"])
    _save_markdown_files(output_dir, profiling_out, adaptive_out, insight_out)
    filename = generate_pdf(data, profiling_out, adaptive_out, insight_out, output_dir)
    print(f"[OK] PDF berhasil dibuat  : {filename}")
    print(f"[>>] Folder output        : {output_dir}/")
    print("     Buka file PDF tersebut untuk cek hasil layout.")
