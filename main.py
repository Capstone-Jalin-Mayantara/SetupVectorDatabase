import os
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Mode Development ──────────────────────────────────────────────────────────
# True  → skip input manual, pakai data dummy
# False → mode normal (input dari guru)
DEV_MODE = True

_DUMMY_DATA = {
    "nama_siswa":    "Budi Santoso",
    "kelas":         "2 SD",
    "mata_pelajaran":"Bahasa Indonesia",
    "gejala": (
        "susah fokus, tidak bisa diam, sering menggerakkan tangan dan kaki, "
        "sulit duduk lama, mudah terdistraksi oleh suara sekitar"
    ),
    "materi_mentah": (
        "Mengenal Huruf Vokal dan Konsonan\n\n"
        "Huruf vokal adalah huruf a, i, u, e, o. Huruf vokal dapat berdiri "
        "sendiri dan membentuk bunyi tanpa bantuan huruf lain. Contoh kata yang "
        "menggunakan huruf vokal: api, ibu, ular, elang, obat.\n\n"
        "Huruf konsonan adalah huruf selain huruf vokal. Contoh huruf konsonan: "
        "b, c, d, f, g, h, j, k, l, m, n, p, q, r, s, t, v, w, x, y, z. "
        "Huruf konsonan biasanya digabungkan dengan huruf vokal untuk membentuk "
        "suku kata. Contoh: ba, bi, bu, be, bo.\n\n"
        "Latihan membaca suku kata:\n"
        "- ba - bi - bu - be - bo\n"
        "- ca - ci - cu - ce - co\n"
        "- da - di - du - de - do\n\n"
        "Siswa diminta membaca nyaring setiap suku kata dan mengulangnya tiga kali."
    ),
}


INPUT_DIR = "input"
_EXTS_OK  = {".docx", ".pdf"}


# ── Markdown table helpers ────────────────────────────────────────────────────

def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2

def _is_sep_row(line: str) -> bool:
    s = line.strip()
    return _is_table_row(s) and all(c in "-|: " for c in s[1:-1])

def _parse_row(line: str) -> list:
    parts = line.strip().split("|")
    return [p.strip() for p in parts[1:-1]]


# Ganti simbol Unicode ke ASCII supaya Helvetica tidak render kotak hitam
_UNICODE_MAP = str.maketrans({
    0x2713: '[v]', 0x2714: '[v]', 0x2705: '[v]',
    0x2717: '[x]', 0x2718: '[x]', 0x274C: '[x]',
    0x2192: '->',  0x2190: '<-',  0x21D2: '=>',
    0x2022: '-',   0x00B7: '-',   0x2023: '-',
    0x2026: '...',
    0x201C: '"',   0x201D: '"',
    0x2018: "'",   0x2019: "'",
    0x2014: '--',  0x2013: '-',
    0x2265: '>=',  0x2264: '<=',  0x2260: '!=',
    0x00D7: 'x',   0x00F7: '/',   0x00B0: 'deg',
    0x26A0: '[!]', 0x2B50: '*',
})


# ── Document loader ───────────────────────────────────────────────────────────

def _list_input_files() -> list:
    if not os.path.isdir(INPUT_DIR):
        return []
    return sorted(
        f for f in os.listdir(INPUT_DIR)
        if os.path.splitext(f)[1].lower() in _EXTS_OK
    )


def _load_document(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".docx":
        from docx import Document
        doc = Document(filepath)
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if ext == ".pdf":
        import pdfplumber
        parts = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
        return "\n\n".join(parts)
    raise ValueError(f"Format file tidak didukung: {ext}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_profil(data: dict) -> str:
    return (
        f"Nama: {data['nama_siswa']} | "
        f"Kelas: {data['kelas']} | "
        f"Mata Pelajaran: {data['mata_pelajaran']} | "
        f"Kondisi/Gejala: {data['gejala']}"
    )


def tanya(label: str, wajib: bool = True) -> str:
    while True:
        nilai = input(f"  {label}: ").strip()
        if nilai or not wajib:
            return nilai
        print("  ⚠️  Input tidak boleh kosong. Coba lagi.")


# ── I/O ───────────────────────────────────────────────────────────────────────

def tampilkan_header():
    print()
    print("=" * 60)
    print("   ASIQ — Sistem Pembuat RPP Inklusif Berbasis AI")
    print("   Universitas Brawijaya | Capstone Project")
    print("=" * 60)
    print()


def _input_materi_manual(mata_pelajaran: str = "", kelas: str = "") -> str:
    print("📄 MATERI PEMBELAJARAN MENTAH")
    print("-" * 40)
    print("  Tempelkan teks materi yang ingin diadaptasi.")
    print("  Ketik SELESAI di baris baru lalu Enter untuk mengakhiri.")
    print()
    baris_materi = []
    while True:
        baris = input()
        if baris.strip().upper() == "SELESAI":
            break
        baris_materi.append(baris)
    materi_mentah = "\n".join(baris_materi).strip()
    if not materi_mentah:
        print("  ⚠️  Materi kosong. Menggunakan placeholder.")
        materi_mentah = f"Materi pelajaran {mata_pelajaran} untuk kelas {kelas}."
    return materi_mentah


def kumpulkan_input_guru() -> dict:
    print("📋 DATA SISWA")
    print("-" * 40)
    nama_siswa     = tanya("Nama siswa")
    kelas          = tanya("Kelas (contoh: 1 SD, 4 SD)")
    mata_pelajaran = tanya("Mata pelajaran (contoh: Bahasa Indonesia)")
    gejala         = tanya("Gejala / kondisi siswa (contoh: susah fokus, tidak bisa diam)")

    print()
    files = _list_input_files()
    if files:
        print("📂 DOKUMEN TERSEDIA DI FOLDER INPUT:")
        print("-" * 40)
        for i, f in enumerate(files, 1):
            print(f"  [{i}] {f}")
        print("  [0] Input teks manual")
        print()
        pilihan = input("  Pilih nomor dokumen (atau 0 untuk manual): ").strip()
        if pilihan.isdigit() and 1 <= int(pilihan) <= len(files):
            path = os.path.join(INPUT_DIR, files[int(pilihan) - 1])
            print(f"\n  📄 Membaca: {files[int(pilihan) - 1]}...")
            materi_mentah = _load_document(path)
            print(f"  ✅ Berhasil dimuat ({len(materi_mentah)} karakter)\n")
        else:
            print()
            materi_mentah = _input_materi_manual(mata_pelajaran, kelas)
    else:
        print()
        materi_mentah = _input_materi_manual(mata_pelajaran, kelas)

    return {
        "nama_siswa": nama_siswa,
        "kelas": kelas,
        "mata_pelajaran": mata_pelajaran,
        "gejala": gejala,
        "materi_mentah": materi_mentah,
    }


# ── Crew ──────────────────────────────────────────────────────────────────────

def jalankan_crew(data: dict):
    from crew import AsiqAgents

    print()
    print("🚀 Menjalankan pipeline ASIQ...")
    print("   [1/3] Profiling Agent  → analisis kondisi siswa")
    print("   [2/3] Adaptive Agent   → adaptasi materi")
    print("   [3/3] Insight Agent    → audit inklusivitas")
    print()

    return AsiqAgents().crew().kickoff(inputs={
        "profil_siswa": _build_profil(data),
        "materi_mentah": data["materi_mentah"],
    })


def tampilkan_hasil(hasil, output_dir: str):
    print()
    print("=" * 60)
    print("✅ SELESAI — Laporan Inklusivitas ASIQ")
    print("=" * 60)
    print()
    print(str(hasil))
    print()
    print(f"📁 Semua output tersimpan di: {output_dir}")
    print("=" * 60)
    print()


# ── Output file management ────────────────────────────────────────────────────

def _create_output_dir(nama_siswa: str) -> str:
    """Buat folder output/YYYYMMDD_HHMMSS_{nama_siswa}/ dan kembalikan path-nya."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = nama_siswa.replace(" ", "_")
    folder = os.path.join("output", f"{ts}_{slug}")
    os.makedirs(folder, exist_ok=True)
    return folder


def _save_markdown_files(output_dir: str, profiling_out: str, adaptive_out: str, insight_out: str):
    """Simpan output ketiga agent sebagai file markdown terpisah."""
    files = {
        "01_Strategi_Profiling.md": profiling_out,
        "02_Materi_Adaptif.md":     adaptive_out,
        "03_Laporan_Audit.md":      insight_out,
    }
    for filename, content in files.items():
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content or "")


# ── PDF Generator ─────────────────────────────────────────────────────────────

def generate_pdf(data: dict, profiling_out: str, adaptive_out: str, insight_out: str, output_dir: str = ".") -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )

    nama   = data["nama_siswa"]
    kelas  = data["kelas"]
    mapel  = data["mata_pelajaran"]
    gejala = data["gejala"]
    now     = datetime.now()
    tanggal = now.strftime("%d %B %Y")
    ts      = now.strftime("%Y%m%d_%H%M%S")

    filename = os.path.join(output_dir, f"RPP_Inklusif_{nama.replace(' ', '_')}_{ts}.pdf")

    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=2 * cm, leftMargin=2 * cm,
        topMargin=2 * cm,   bottomMargin=2 * cm,
    )

    W = A4[0] - 4 * cm          # lebar efektif halaman
    BLUE      = colors.HexColor("#1565C0")
    BLUE_DARK = colors.HexColor("#0D3B86")
    BLUE_LITE = colors.HexColor("#E3F2FD")
    GRAY      = colors.HexColor("#546E7A")

    base = getSampleStyleSheet()

    s_title = ParagraphStyle("s_title", parent=base["Normal"],
        fontSize=13, fontName="Helvetica-Bold",
        textColor=colors.white, alignment=TA_CENTER)

    s_subtitle = ParagraphStyle("s_subtitle", parent=base["Normal"],
        fontSize=9, fontName="Helvetica",
        textColor=colors.HexColor("#BBDEFB"), alignment=TA_CENTER)

    s_section = ParagraphStyle("s_section", parent=base["Normal"],
        fontSize=10, fontName="Helvetica-Bold",
        textColor=colors.white, alignment=TA_LEFT)

    s_key = ParagraphStyle("s_key", parent=base["Normal"],
        fontSize=9.5, fontName="Helvetica-Bold",
        textColor=BLUE_DARK)

    s_val = ParagraphStyle("s_val", parent=base["Normal"],
        fontSize=9.5, fontName="Helvetica",
        textColor=colors.black)

    s_body = ParagraphStyle("s_body", parent=base["Normal"],
        fontSize=9.5, fontName="Helvetica",
        textColor=colors.black, alignment=TA_JUSTIFY,
        leading=14, spaceAfter=2)

    s_footer = ParagraphStyle("s_footer", parent=base["Normal"],
        fontSize=8, fontName="Helvetica",
        textColor=GRAY, alignment=TA_CENTER)

    s_h2 = ParagraphStyle("s_h2", parent=base["Normal"],
        fontSize=10.5, fontName="Helvetica-Bold",
        textColor=BLUE_DARK, spaceBefore=6, spaceAfter=2)

    s_h3 = ParagraphStyle("s_h3", parent=base["Normal"],
        fontSize=9.5, fontName="Helvetica-Bold",
        textColor=BLUE_DARK, spaceBefore=4, spaceAfter=2)

    s_th = ParagraphStyle("s_th", parent=base["Normal"],
        fontSize=8.5, fontName="Helvetica-Bold",
        textColor=colors.white, leading=11)

    s_td = ParagraphStyle("s_td", parent=base["Normal"],
        fontSize=8.5, fontName="Helvetica",
        textColor=colors.black, leading=11)

    s_img = ParagraphStyle("s_img", parent=base["Normal"],
        fontSize=8.5, fontName="Helvetica-Oblique",
        textColor=GRAY, alignment=TA_CENTER)

    # ── Fungsi bantu ──
    _RE_NON_LATIN  = re.compile("[^\x00-\xFF]")
    _RE_BOLD       = re.compile(r"\*\*(.*?)\*\*")
    _RE_ITALIC     = re.compile(r"\*(.*?)\*")
    _RE_HEADER     = re.compile(r"^#{1,4}\s+")

    def _clean(text: str) -> str:
        text = text.translate(_UNICODE_MAP)
        text = _RE_NON_LATIN.sub("", text)
        text = text.replace("<br>", "%%BR%%").replace("<br/>", "%%BR%%")
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace("%%BR%%", "<br/>")
        text = _RE_BOLD.sub(r"<b>\1</b>", text)
        text = _RE_ITALIC.sub(r"<i>\1</i>", text)
        text = _RE_HEADER.sub("", text)
        return text

    def _section_bar(letter: str, title: str):
        t = Table([[Paragraph(f"<b>{letter}. {title.upper()}</b>", s_section)]],
                  colWidths=[W])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), BLUE),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("BOX",           (0, 0), (-1, -1), 0.5, BLUE_DARK),
        ]))
        return t

    def _add_content(story: list, text: str):
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            i += 1

            # Skip blank lines
            if not stripped:
                story.append(Spacer(1, 0.10 * cm))
                continue

            # Skip horizontal rules dan section markers AI (---, --, --\n1 dst)
            if re.match(r"^-{2,}$", stripped) or stripped == "--":
                continue

            # Skip angka section artifact dari AI (1, 2, ... 15)
            if re.match(r"^\d{1,2}$", stripped):
                continue

            # Skip baris yang hanya berisi |
            if stripped == "|":
                continue

            # Markdown table block
            if _is_table_row(stripped):
                rows = []
                j = i - 1  # mundur satu karena sudah increment
                while j < len(lines) and _is_table_row(lines[j].strip()):
                    if not _is_sep_row(lines[j]):
                        row = _parse_row(lines[j])
                        if any(cell for cell in row):
                            rows.append(row)
                    j += 1
                i = j

                if rows:
                    n_cols = max(len(r) for r in rows)
                    rows = [r + [""] * (n_cols - len(r)) for r in rows]
                    col_w = W / n_cols
                    tbl_data = []
                    for ri, row in enumerate(rows):
                        style = s_th if ri == 0 else s_td
                        tbl_data.append([Paragraph(_clean(c), style) for c in row])
                    tbl = Table(tbl_data, colWidths=[col_w] * n_cols, repeatRows=1)
                    tbl.setStyle(TableStyle([
                        ("BACKGROUND",    (0, 0), (-1, 0),  BLUE),
                        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, BLUE_LITE]),
                        ("BOX",           (0, 0), (-1, -1), 0.8, BLUE),
                        ("INNERGRID",     (0, 0), (-1, -1), 0.3, colors.HexColor("#BBDEFB")),
                        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING",    (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
                    ]))
                    story.append(tbl)
                    story.append(Spacer(1, 0.2 * cm))
                continue

            # Markdown headers (## atau ###)
            m = re.match(r"^(#{1,4})\s+(.*)", stripped)
            if m:
                level = len(m.group(1))
                content = re.sub(r"\*\*(.*?)\*\*", r"\1", m.group(2))
                story.append(Paragraph(_clean(content), s_h2 if level <= 2 else s_h3))
                continue

            # Placeholder gambar — deteksi **Gambar N:** atau [Gambar N]
            img_m = re.match(r"^\*{0,2}Gambar\s+\d+[.:)]\*{0,2}\s*(.*)", stripped, re.IGNORECASE)
            if not img_m:
                img_m = re.match(r"^\[Gambar\s+\d+\]\s*(.*)", stripped, re.IGNORECASE)
            if img_m:
                caption = img_m.group(1).strip() or "Ilustrasi"
                caption = re.sub(r"\*\*(.*?)\*\*", r"\1", caption)
                ph = Table(
                    [[Paragraph(f"[ Gambar: {_clean(caption)} ]", s_img)]],
                    colWidths=[W],
                )
                ph.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#F5F5F5")),
                    ("BOX",           (0, 0), (-1, -1), 0.8, colors.HexColor("#BDBDBD")),
                    ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING",    (0, 0), (-1, -1), 18),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
                ]))
                story.append(ph)
                story.append(Spacer(1, 0.2 * cm))
                continue

            # Paragraph biasa
            story.append(Paragraph(_clean(stripped), s_body))

    # ── Story ──
    story = []

    # Header formal RPP
    header_rows = [
        [Paragraph("RENCANA PELAKSANAAN PEMBELAJARAN INKLUSIF", s_title)],
        [Paragraph("Sistem ASIQ &mdash; Adaptive Student Inclusive Learning", s_subtitle)],
        [Paragraph("Universitas Brawijaya &bull; Capstone Project 2026", s_subtitle)],
    ]
    header_tbl = Table(header_rows, colWidths=[W])
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), BLUE_DARK),
        ("BACKGROUND",    (0, 1), (0, 2), BLUE),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (0, 0), 12),
        ("BOTTOMPADDING", (0, 0), (0, 0), 10),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("BOX",           (0, 0), (-1, -1), 2, BLUE_DARK),
        ("LINEBELOW",     (0, 0), (0, 0), 1, colors.white),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 0.35 * cm))

    # Tabel identitas siswa (format RPP) — 2 kolom, colon di kolom value
    gejala_short = gejala if len(gejala) <= 90 else gejala[:87] + "..."
    identity_rows = [
        [Paragraph("Satuan Pendidikan",          s_key), Paragraph(": SDN / SLB Inklusif", s_val)],
        [Paragraph("Kelas / Semester",           s_key), Paragraph(f": {kelas}",           s_val)],
        [Paragraph("Mata Pelajaran",             s_key), Paragraph(f": {mapel}",            s_val)],
        [Paragraph("Nama Siswa",                 s_key), Paragraph(f": {nama}",             s_val)],
        [Paragraph("Kondisi / Kebutuhan Khusus", s_key), Paragraph(f": {gejala_short}",     s_val)],
        [Paragraph("Tanggal Generate",           s_key), Paragraph(f": {tanggal}",          s_val)],
    ]
    id_col = [6.0 * cm, W - 6.0 * cm]
    identity_tbl = Table(identity_rows, colWidths=id_col)
    identity_tbl.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 1.2, BLUE),
        ("INNERGRID",     (0, 0), (-1, -1), 0.4, colors.HexColor("#BBDEFB")),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1), [colors.white, BLUE_LITE]),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(identity_tbl)
    story.append(Spacer(1, 0.45 * cm))

    # Bagian A — Profil & Strategi
    story.append(_section_bar("A", "Profil Siswa & Strategi Adaptasi"))
    story.append(Spacer(1, 0.2 * cm))
    _add_content(story, profiling_out or "(output profiling tidak tersedia)")
    story.append(Spacer(1, 0.45 * cm))

    # Bagian B — Materi Adaptif
    story.append(_section_bar("B", "Materi Pembelajaran Adaptif"))
    story.append(Spacer(1, 0.2 * cm))
    _add_content(story, adaptive_out or "(output materi adaptif tidak tersedia)")
    story.append(Spacer(1, 0.45 * cm))

    # Bagian C — Laporan Audit
    story.append(_section_bar("C", "Laporan Audit Inklusivitas"))
    story.append(Spacer(1, 0.2 * cm))
    _add_content(story, insight_out or "(output laporan audit tidak tersedia)")
    story.append(Spacer(1, 0.5 * cm))

    # Footer
    story.append(HRFlowable(width=W, thickness=1, color=BLUE))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        f"Generated by ASIQ &bull; Universitas Brawijaya &bull; {tanggal}",
        s_footer
    ))

    doc.build(story)
    return filename


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    tampilkan_header()

    if DEV_MODE:
        print("⚡ DEV_MODE aktif — skip input manual.\n")
        data = _DUMMY_DATA.copy()
        files = _list_input_files()
        if files:
            path = os.path.join(INPUT_DIR, files[0])
            print(f"  📄 Auto-load dokumen: {files[0]}")
            data["materi_mentah"] = _load_document(path)
            print(f"  ✅ Materi dimuat ({len(data['materi_mentah'])} karakter)\n")
    else:
        data = kumpulkan_input_guru()
        profil_preview = _build_profil(data)
        print()
        print("🔄 Konfirmasi input:")
        print(f"   Profil : {profil_preview}")
        print(f"   Materi : {data['materi_mentah'][:80]}{'...' if len(data['materi_mentah']) > 80 else ''}")
        print()
        if input("   Lanjutkan? (y/n): ").strip().lower() != "y":
            print("\n❌ Dibatalkan oleh pengguna.")
            return

    output_dir = _create_output_dir(data["nama_siswa"])

    hasil = jalankan_crew(data)

    # Ambil output tiap agent dari CrewOutput
    try:
        profiling_out = hasil.tasks_output[0].raw
        adaptive_out  = hasil.tasks_output[1].raw
        insight_out   = hasil.tasks_output[2].raw
    except (AttributeError, IndexError):
        profiling_out = str(hasil)
        adaptive_out  = ""
        insight_out   = ""

    _save_markdown_files(output_dir, profiling_out, adaptive_out, insight_out)
    pdf_file = generate_pdf(data, profiling_out, adaptive_out, insight_out, output_dir)

    tampilkan_hasil(hasil, output_dir)
    print(f"📄 PDF  : {pdf_file}")
    print(f"📂 Folder: {output_dir}/")
    print()


if __name__ == "__main__":
    main()
