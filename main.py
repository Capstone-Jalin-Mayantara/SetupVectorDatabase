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


# Sanitasi Unicode untuk PDF.
# _TYPO_MAP : simbol tipografi → padanan teks (selalu diterapkan).
# _EMOJI_TXT: fallback emoji → teks, dipakai PER KARAKTER hanya bila
#             font emoji tidak tersedia atau glyph tidak ada di font.
#             Bila font emoji (Segoe UI Emoji) terdaftar, emoji dirender
#             sebagai ikon asli via tag <font> di _clean.
_TYPO_MAP = str.maketrans({
    0x2192: '->',   0x2190: '<-',   0x21D2: '=>',   0x21A6: '->',
    0x2194: '<->',
    0x2022: '-',    0x00B7: '-',    0x2023: '-',    0x2043: '-',
    0x2026: '...',
    0x201C: '"',    0x201D: '"',    0x00AB: '"',    0x00BB: '"',
    0x2018: "'",    0x2019: "'",    0x02BC: "'",
    0x2014: '-',    0x2013: '-',    0x2012: '-',
    0x2011: '-',    0x2212: '-',
    0x2265: '>=',   0x2264: '<=',   0x2260: '!=',   0x2248: '~=',
    0x00D7: 'x',    0x00F7: '/',    0x00B0: 'deg',  0x00B2: '2',  0x00B3: '3',
    0x00A0: ' ',    0x00AD: '',     0x200B: '',     0x200C: '',
    0x200D: '',     0xFEFF: '',     0xFE0F: '',     0x20E3: '',
})

_EMOJI_TXT = {
    0x2713: '[v]',  0x2714: '[v]',  0x2705: '[v]',  0x2611: '[v]',
    0x2717: '[x]',  0x2718: '[x]',  0x274C: '[x]',  0x2612: '[x]',
    0x2610: '[ ]',  0x25A1: '[ ]',  0x26A0: '[!]',
    0x25B6: '>',    0x25C0: '<',    0x25A0: '[#]',
}


# ── Emoji berwarna (Twemoji PNG) ──────────────────────────────────────────────
# Emoji dirender sebagai gambar PNG berwarna (Twemoji) yang disisipkan inline
# lewat tag <img> di Paragraph. PNG di-download sekali per emoji lalu di-cache
# di assets/emoji_cache/ — setelah itu berfungsi offline.
# Urutan fallback per karakter: PNG berwarna → glyph font emoji (monokrom)
# → teks ([v], [!], dst.) → dibuang.
_EMOJI_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "assets", "emoji_cache")
_TWEMOJI_URL   = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/72x72/{}.png"
_emoji_failed  = set()    # codepoint yang gagal di-download (cache per proses)
_emoji_netdown = False    # True bila jaringan mati → jangan coba download lagi


def _emoji_png(cp: int):
    """Path PNG Twemoji berwarna untuk satu codepoint, atau None bila tak ada."""
    global _emoji_netdown
    if cp in _emoji_failed:
        return None
    path = os.path.join(_EMOJI_DIR, f"{cp:x}.png")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    if _emoji_netdown:
        return None
    try:
        import urllib.request
        os.makedirs(_EMOJI_DIR, exist_ok=True)
        with urllib.request.urlopen(_TWEMOJI_URL.format(f"{cp:x}"), timeout=6) as r:
            data = r.read()
        with open(path, "wb") as fh:
            fh.write(data)
        return path
    except Exception as e:
        _emoji_failed.add(cp)
        import urllib.error
        # HTTPError (404) = emoji memang tak ada di Twemoji; selain itu
        # anggap jaringan bermasalah → hentikan percobaan download berikutnya
        if not isinstance(e, urllib.error.HTTPError):
            _emoji_netdown = True
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return None


# ── Illustration cache (Pollinations.ai) ──────────────────────────────────────
_IMG_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "img_cache")
_POLL_HOST  = "gen.pollinations.ai"
_POLL_TOKEN = os.getenv("POLLINATIONS_TOKEN", "")
_img_failed: set = set()


# Suffix anti-teks — SELALU ditambahkan di sisi kode, tidak bergantung output Groq.
# FLUX cenderung menggambar tulisan bila prompt menyebut tema pelajaran; suffix ini
# + prompt yang murni visual (tanpa menyebut nama mapel) menekan kemunculan teks.
_IMG_NO_TEXT = (", wordless textless illustration, absolutely no text, no words, "
                "no letters, no captions, no labels, no signage, no typography, "
                "no writing anywhere, plain background")


def _generate_illustration(prompt: str, width: int = 800, height: int = 500):
    """Download ilustrasi dari Pollinations, cache di assets/img_cache/. Return path atau None."""
    import hashlib, http.client, urllib.parse
    global _img_failed
    prompt = prompt.rstrip(". ") + _IMG_NO_TEXT
    key  = hashlib.md5(prompt.encode()).hexdigest()
    path = os.path.join(_IMG_DIR, f"{key}.jpg")
    if os.path.exists(path) and os.path.getsize(path) > 5000:
        return path
    if key in _img_failed:
        return None
    try:
        os.makedirs(_IMG_DIR, exist_ok=True)
        encoded = urllib.parse.quote(prompt)
        p = f"/image/{encoded}?model=flux&width={width}&height={height}&seed=-1&nologo=true"
        headers = {"User-Agent": "ASIQ-PDF/1.0"}
        if _POLL_TOKEN:
            headers["Authorization"] = f"Bearer {_POLL_TOKEN}"
        conn = http.client.HTTPSConnection(_POLL_HOST, timeout=60)
        conn.request("GET", p, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        if resp.status == 200 and len(data) > 5000:
            with open(path, "wb") as f:
                f.write(data)
            return path
        _img_failed.add(key)
        return None
    except Exception:
        _img_failed.add(key)
        return None


def _fetch_image_prompts(mapel: str, kelas: str, kebutuhan: str) -> list:
    """Minta Groq buat 2 prompt ilustrasi dalam bahasa Inggris. Fallback ke prompt statis."""
    import json
    try:
        import litellm
        _or_key = os.getenv("OPENROUTER_API_KEY", "")
        resp = litellm.completion(
            api_key=_or_key or os.getenv("GROQ_API_KEY", ""),
            model=("openrouter/openai/gpt-oss-120b" if _or_key
                   else "groq/openai/gpt-oss-120b"),   # model sama dgn pipeline utama
            messages=[{"role": "user", "content": (
                f"Create 2 short English image prompts for illustrations in a children's PDF.\n"
                f"Topic context: {mapel} | Grade: {kelas} | Special needs: {kebutuhan}\n\n"
                f"STRICT RULES — the image generator draws ugly garbled text whenever "
                f"a prompt hints at words, so:\n"
                f"- Describe ONLY a visual scene: people, objects, actions, expressions, colors.\n"
                f"- NEVER mention the subject name, titles, posters, signs, alphabets, "
                f"letters, blackboards/whiteboards with writing, or open books with visible pages.\n"
                f"- Good example: 'happy children sitting in a circle listening to their "
                f"teacher telling a story, flat cartoon style, white background'\n"
                f"- Prompt 1: children doing a fun activity related to the topic (visually).\n"
                f"- Prompt 2: colorful objects/scene representing the topic (visually).\n"
                f"- Style: flat cartoon, colorful, child-friendly, white background.\n"
                f"Return ONLY a JSON array: [\"prompt1\", \"prompt2\"]"
            )}],
            max_tokens=1200,   # gpt-oss = reasoning model, butuh ruang utk berpikir
            temperature=0.7,
        )
        text = resp.choices[0].message.content.strip()
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if m:
            prompts = json.loads(m.group(0))
            return [p for p in prompts if isinstance(p, str)][:2]
    except Exception as e:
        print(f"  [IMG] Groq prompt gagal: {e}")
    # Fallback statis: deskripsi visual murni — tidak menyebut nama mapel
    # supaya model gambar tidak terpancing menulis judul.
    return [
        "Cheerful Indonesian elementary school children sitting in a classroom, "
        "raising hands and smiling at their teacher, flat cartoon style, colorful, "
        "child-friendly, white background",
        "Happy children playing and listening to a story together under a tree, "
        "colorful flat cartoon illustration, child-friendly, white background",
    ]


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
    from crew import run_crew_with_retry

    print()
    print("🚀 Menjalankan pipeline ASIQ...")
    print("   [1/3] Profiling Agent  → analisis kondisi siswa")
    print("   [2/3] Adaptive Agent   → adaptasi materi")
    print("   [3/3] Insight Agent    → audit inklusivitas")
    print()

    return run_crew_with_retry(inputs={
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

def generate_pdf(data: dict, profiling_out: str, adaptive_out: str, insight_out: str, output_dir: str = ".", illustrations: list = None) -> str:
    """
    Generate PDF RPP Inklusif.
    Dicetak ke PDF : Section A (Profil & Strategi) + Section B (Materi Adaptif).
    Section C (Audit Inklusivitas) TIDAK dicetak — hanya tersedia via API response
    dan file 03_Laporan_Audit.md.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate,
        NextPageTemplate, PageBreak,
        Paragraph, Spacer, Table, TableStyle, Image,
        HRFlowable, KeepTogether, Flowable,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # ── Data ─────────────────────────────────────────────────────────────────
    nama    = data["nama_siswa"]
    kelas   = data["kelas"]
    mapel   = data["mata_pelajaran"]
    gejala  = data["gejala"]
    now     = datetime.now()
    tanggal = now.strftime("%d %B %Y")
    ts      = now.strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_dir, f"RPP_Inklusif_{nama.replace(' ', '_')}_{ts}.pdf")

    # ── Geometri halaman ─────────────────────────────────────────────────────
    PW, PH = A4
    MARGIN  = 1.8 * cm

    # ── Asset paths ───────────────────────────────────────────────────────────
    ASSETS   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    COVER_BG = os.path.join(ASSETS, "cover_bg.png")
    HEADER   = os.path.join(ASSETS, "header.png")
    FOOTER   = os.path.join(ASSETS, "footer.png")
    LOGO_UB  = os.path.join(ASSETS, "Logo_Universitas_Brawijaya.png")
    LOGO_FK  = os.path.join(ASSETS, "logo_filkom.png")
    LOGO_JM  = os.path.join(ASSETS, "logo_jalin-mayantara.png")

    def _img_h(path: str, draw_w: float, default: float) -> float:
        """Hitung tinggi proporsional gambar pada lebar draw_w."""
        if not os.path.exists(path):
            return default
        try:
            from PIL import Image as PILImg
            with PILImg.open(path) as im:
                iw, ih = im.size
                return (ih / iw) * draw_w
        except Exception:
            return default

    HEADER_H = _img_h(HEADER, PW, 2.4 * cm)
    FOOTER_H = _img_h(FOOTER, PW, 1.6 * cm)

    # ── Font (coba Unicode TTF, fallback Helvetica) ───────────────────────────
    FONT_N, FONT_B, FONT_I = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
    _font_candidates = [
        ("C:/Windows/Fonts/calibri.ttf",  "C:/Windows/Fonts/calibrib.ttf",  "CaliU"),
        ("C:/Windows/Fonts/arial.ttf",    "C:/Windows/Fonts/arialbd.ttf",   "ArialU"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",            "DejaVuU"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",    "LibU"),
    ]
    for _np, _bp, _nm in _font_candidates:
        if os.path.exists(_np):
            try:
                pdfmetrics.registerFont(TTFont(_nm, _np))
                FONT_N, FONT_I = _nm, _nm
                if os.path.exists(_bp):
                    pdfmetrics.registerFont(TTFont(_nm + "B", _bp))
                    FONT_B = _nm + "B"
                else:
                    FONT_B = _nm
                break
            except Exception:
                continue

    # ── Font emoji (untuk render ikon 😊 📚 ⏰ dsb. dari output AI) ──────────
    FONT_E      = None
    _EMOJI_CMAP = {}
    _emoji_candidates = [
        ("C:/Windows/Fonts/seguiemj.ttf",                              "SegoeEmoji"),
        ("C:/Windows/Fonts/seguisym.ttf",                              "SegoeSym"),
        ("/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",       "NotoEmoji"),
        ("/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf", "Symbola"),
    ]
    for _ep, _enm in _emoji_candidates:
        if os.path.exists(_ep):
            try:
                pdfmetrics.registerFont(TTFont(_enm, _ep))
                FONT_E      = _enm
                _EMOJI_CMAP = pdfmetrics.getFont(_enm).face.charToGlyph
                break
            except Exception:
                continue

    # ── Warna ─────────────────────────────────────────────────────────────────
    C_ORANGE  = colors.HexColor("#F5A623")
    C_ORANGE_L = colors.HexColor("#FFF8EC")
    C_NAVY    = colors.HexColor("#1B3A6B")
    C_BLUE    = colors.HexColor("#1565C0")
    C_DARK    = colors.HexColor("#0D3B86")
    C_MID     = colors.HexColor("#1976D2")
    C_LITE    = colors.HexColor("#E3F2FD")
    C_GRAY    = colors.HexColor("#546E7A")
    C_GRAYL   = colors.HexColor("#ECEFF1")
    C_WHITE   = colors.white
    C_BLACK   = colors.black

    W = PW - 2 * MARGIN  # lebar konten efektif

    # ── Style factory ─────────────────────────────────────────────────────────
    _base = getSampleStyleSheet()

    def _S(name, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, parent=_base["Normal"], **kw)

    # Konten
    S_BODY   = _S("body",   fontName=FONT_N, fontSize=9.5, leading=14,
                            textColor=C_BLACK, alignment=TA_JUSTIFY, spaceAfter=2)
    S_BULLET = _S("bullet", fontName=FONT_N, fontSize=9.5, leading=14,
                            textColor=C_BLACK, leftIndent=14, spaceAfter=1)
    S_NUM    = _S("num",    fontName=FONT_N, fontSize=9.5, leading=14,
                            textColor=C_BLACK, leftIndent=22,
                            firstLineIndent=-22, spaceAfter=1)
    S_CHECK  = _S("check",  fontName=FONT_N, fontSize=9.5, leading=14,
                            textColor=C_BLACK, leftIndent=14, spaceAfter=1)
    S_H2     = _S("h2",     fontName=FONT_B, fontSize=11.5, leading=15,
                            textColor=C_NAVY, spaceBefore=8, spaceAfter=3)
    S_H3     = _S("h3",     fontName=FONT_B, fontSize=10.5, leading=14,
                            textColor=C_NAVY, spaceBefore=6, spaceAfter=2)
    S_H4     = _S("h4",     fontName=FONT_B, fontSize=9.5,  leading=13,
                            textColor=C_BLUE, spaceBefore=4, spaceAfter=2)
    S_BLABEL = _S("blabel", fontName=FONT_B, fontSize=9.5,  leading=13,
                            textColor=C_NAVY, spaceAfter=1)
    S_QUOTE  = _S("quote",  fontName=FONT_I, fontSize=9.5,  leading=14,
                            textColor=C_GRAY, leftIndent=16, spaceAfter=2)
    S_IMG    = _S("img",    fontName=FONT_I, fontSize=8.5,  leading=11,
                            textColor=C_GRAY, alignment=TA_CENTER)
    S_TH     = _S("th",     fontName=FONT_B, fontSize=8.5,  leading=11,
                            textColor=C_WHITE)
    S_TD     = _S("td",     fontName=FONT_N, fontSize=8.5,  leading=11,
                            textColor=C_BLACK)
    # Section header
    S_SEC_T  = _S("sect",   fontName=FONT_B, fontSize=13,   leading=17,
                            textColor=C_NAVY)
    S_SEC_R  = _S("secr",   fontName=FONT_N, fontSize=7.5,  leading=10,
                            textColor=C_GRAY, alignment=TA_RIGHT)
    # Cover
    S_BIG_T  = _S("bigt",   fontName=FONT_B, fontSize=22,   leading=27,
                            textColor=C_NAVY, alignment=TA_CENTER)
    S_COV_D  = _S("covd",   fontName=FONT_N, fontSize=10,   leading=14,
                            textColor=C_GRAY, alignment=TA_CENTER)
    S_COV_FT = _S("covft",  fontName=FONT_N, fontSize=8.5,  leading=11,
                            textColor=C_GRAY, alignment=TA_CENTER)
    S_ID_K   = _S("idk",    fontName=FONT_B, fontSize=9.5,  leading=13,
                            textColor=C_NAVY)
    S_ID_V   = _S("idv",    fontName=FONT_N, fontSize=9.5,  leading=13,
                            textColor=C_BLACK)

    # ── PillBadge: flowable dengan rounded rectangle ──────────────────────────
    class _PillBadge(Flowable):
        def __init__(self, text, fn, fs, bg, tc,
                     px=10, py=4, align='LEFT', cw=None):
            Flowable.__init__(self)
            self._text = text
            self._fn = fn;   self._fs = fs
            self._bg = bg;   self._tc = tc
            self._px = px;   self._py = py
            self._align = align
            tw         = pdfmetrics.stringWidth(text, fn, fs)
            self._bw   = tw + 2 * px
            self._bh   = fs + 2 * py
            self.width = cw or self._bw
            self.height = self._bh + 2

        def draw(self):
            c = self.canv
            bw, bh = self._bw, self._bh
            x = {'CENTER': (self.width - bw) / 2,
                 'RIGHT':  self.width - bw}.get(self._align, 0)
            c.saveState()
            c.setFillColor(self._bg)
            c.roundRect(x, 1, bw, bh, bh / 2, stroke=0, fill=1)
            c.setFillColor(self._tc)
            c.setFont(self._fn, self._fs)
            c.drawCentredString(x + bw / 2,
                                1 + (bh - self._fs) / 2 + 0.5,
                                self._text)
            c.restoreState()

    # ── Text cleaner ──────────────────────────────────────────────────────────
    _RE_SUPPL = re.compile(r"[\U00010000-\U0010FFFF]")
    _RE_HDR   = re.compile(r"^#{1,4}\s+")
    # Rentang karakter emoji/piktograf yang dirender dengan font emoji
    _RE_EMOJI = re.compile(
        r"[⌀-⏿■-◿☀-➿⬀-⯿"
        r"\U0001F000-\U0001FAFF]+"
    )

    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _emojify(m: "re.Match") -> str:
        """Render emoji: PNG berwarna → glyph font (monokrom) → teks → buang."""
        out = []
        for ch in m.group(0):
            if ch.isspace():
                out.append(ch)
                continue
            cp  = ord(ch)
            png = _emoji_png(cp)
            if png:
                out.append(f'<img src="{png}" width="11" height="11" valign="-2"/>')
            elif FONT_E and cp in _EMOJI_CMAP:
                out.append(f'<font name="{FONT_E}">{ch}</font>')
            elif cp in _EMOJI_TXT:
                out.append(_EMOJI_TXT[cp])
            # else: glyph tidak tersedia → dibuang
        return "".join(out)

    def _clean(text: str) -> str:
        """Sanitasi teks output AI untuk ReportLab Paragraph."""
        text = text.translate(_TYPO_MAP)
        if not FONT_E:
            # Tanpa font emoji: ganti ke teks, buang sisa supplementary plane
            text = text.translate(str.maketrans(_EMOJI_TXT))
            text = _RE_SUPPL.sub("", text)
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # <br> dari AI (sering dipakai di sel tabel) → line break ReportLab
        text = re.sub(r"&lt;br\s*/?&gt;", "<br/>", text, flags=re.IGNORECASE)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = text.replace("**", "")   # sisa ** tak berpasangan: jangan tercetak
        text = re.sub(r"\*(.+?)\*",     r"<i>\1</i>", text)
        text = re.sub(r"\[_{1,}\]",     "<u>___________</u>", text)
        text = re.sub(r"_{4,}",         "<u>___________</u>", text)
        text = _RE_HDR.sub("", text)
        # Rapikan spasi ganda
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\(\s+", "(", text)
        text = re.sub(r"\s+\)", ")", text)
        # Terakhir: bungkus emoji dengan font emoji (setelah escape & markup)
        text = _RE_EMOJI.sub(_emojify, text)
        return text.strip()

    def _preprocess(text: str) -> str:
        """Bersihkan artefak agent & normalisasi struktur sebelum parsing baris."""
        if not text:
            return text
        text = text.strip()
        # "Final Answer:" paling andal — ambil semua SETELAH kemunculan terakhir
        if "Final Answer:" in text:
            text = text.split("Final Answer:")[-1].lstrip()
        # Bocoran JSON tool-call di awal output: {"query": {...}}{"result": "..."}<konten>
        # Buang setiap objek JSON utuh di depan (kurung kurawal diseimbangkan,
        # kurung di dalam string di-skip) sampai ketemu konten asli.
        while text.startswith("{"):
            depth, in_str, esc, end = 0, False, False, -1
            for i, ch in enumerate(text):
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = not in_str
                elif not in_str:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
            if end == -1:
                break   # JSON tidak utuh — biarkan, jangan buang konten
            text = text[end + 1:].lstrip()
        # Baris skor mesin (READABILITY_SCORE: 78) untuk parser API — jangan dicetak
        text = re.sub(r"^\**\s*(READABILITY_SCORE|INCLUSIVITY_SCORE)\s*[:=][^\n]*$", "",
                      text, flags=re.MULTILINE | re.IGNORECASE)
        # Jejak ReAct bocor di awal output: "Thought: ... Observation: {json}
        # Thought: ... <jawaban asli>". Buang semuanya sampai konten asli —
        # konten asli dikenali dari marker markdown pertama (** / # / | / -)
        # setelah "Thought:" TERAKHIR.
        if text.startswith(("Thought:", "Observation:")):
            idx  = text.rfind("Thought:")
            tail = text[idx:] if idx != -1 else text
            m = re.search(r"(\*\*|\n#{1,4}\s|\n\||\n- )", tail)
            if m:
                text = tail[m.start():].lstrip()
            else:
                # fallback: buang baris pertama (kalimat thought) saja
                text = re.sub(r"^(Thought|Observation):[^\n]*\n?", "", tail).lstrip()
        # Echo instruksi panjang ("*(Total <= 200 kata)*") tidak perlu dicetak
        text = re.sub(r"^\**\(Total[^\n)]*kata\)\**[ \t]*$", "", text,
                      flags=re.MULTILINE | re.IGNORECASE)
        # Bold judul 2 baris ("** judul\nbaris dua**") → bold per baris.
        # Regex SANGAT ketat: pembuka harus di awal baris, penutup di akhir
        # baris berikutnya, tanpa |/#/asterisk di dalamnya — supaya **
        # nyasar (tak berpasangan) tidak dijodohkan lintas-bagian dan
        # merusak tabel/heading.
        text = re.sub(
            r"^\*\* ?([^*\n|#]{1,100})\n([^*\n|#]{1,100}?) ?\*\*[ \t]*$",
            lambda m: f"**{m.group(1).strip()}**\n**{m.group(2).strip()}**",
            text, flags=re.MULTILINE,
        )
        # Keycap "1️⃣" → "1." agar terbaca sebagai numbered list / heading
        text = re.sub(r"(\d)️?⃣\s*", r"\1. ", text)
        # Emoji diamond/separator (🔸🔹🔶🔷…) → pecah jadi bullet baris baru
        text = re.sub(r"\s*[\U0001F536-\U0001F53B]\s*", "\n- ", text)
        return text

    # ── Section bar (orange badge + judul + info kanan + garis biru) ──────────
    def _sec_bar(letter: str, title: str,
                 right_top: str = "", right_bot: str = ""):
        BAD_COL = 2.4 * cm
        RGT_COL = 3.6 * cm
        TTL_COL = W - BAD_COL - RGT_COL

        badge = _PillBadge(f"BAGIAN {letter}", FONT_B, 7.5,
                           C_ORANGE, C_WHITE, px=9, py=4,
                           align='LEFT', cw=BAD_COL)

        right_txt = _esc(right_top)
        if right_bot:
            right_txt += f"<br/>{_esc(right_bot)}"

        hdr = Table(
            [[badge,
              Paragraph(f"<b>{_esc(title)}</b>", S_SEC_T),
              Paragraph(right_txt, S_SEC_R) if right_txt else Spacer(RGT_COL, 0.1*cm)]],
            colWidths=[BAD_COL, TTL_COL, RGT_COL],
        )
        hdr.setStyle(TableStyle([
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING",   (0,0), (-1,-1), 0),
            ("RIGHTPADDING",  (0,0), (-1,-1), 0),
        ]))
        return KeepTogether([
            Spacer(1, 0.2 * cm),
            hdr,
            HRFlowable(width=W, thickness=1.5, color=C_BLUE,
                       spaceBefore=0.1*cm, spaceAfter=0.15*cm),
        ])

    # ── Placeholder gambar ────────────────────────────────────────────────────
    def _img_box(caption: str):
        ph = Table([[Paragraph(f"[ Gambar: {_clean(caption)} ]", S_IMG)]], colWidths=[W])
        ph.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), C_GRAYL),
            ("BOX",           (0,0), (-1,-1), 1.0, colors.HexColor("#BDBDBD")),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("TOPPADDING",    (0,0), (-1,-1), 16),
            ("BOTTOMPADDING", (0,0), (-1,-1), 16),
        ]))
        return ph

    # ── Markdown table renderer ───────────────────────────────────────────────
    def _md_table(rows: list):
        if not rows:
            return None
        nc   = max(len(r) for r in rows)
        rows = [r + [""] * (nc - len(r)) for r in rows]
        cw   = W / nc
        tbl_data = []
        for ri, row in enumerate(rows):
            st = S_TH if ri == 0 else S_TD
            tbl_data.append([Paragraph(_clean(c), st) for c in row])
        tbl = Table(tbl_data, colWidths=[cw] * nc, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0,0), (-1,0),  C_BLUE),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_WHITE, C_LITE]),
            ("BOX",            (0,0), (-1,-1), 0.8, C_BLUE),
            ("INNERGRID",      (0,0), (-1,-1), 0.3, colors.HexColor("#BBDEFB")),
            ("VALIGN",         (0,0), (-1,-1), "TOP"),
            ("TOPPADDING",     (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 4),
            ("LEFTPADDING",    (0,0), (-1,-1), 5),
            ("RIGHTPADDING",   (0,0), (-1,-1), 5),
        ]))
        return tbl

    # ── Content parser ────────────────────────────────────────────────────────
    def _add_content(story: list, text: str):
        if not text:
            return
        text          = _preprocess(text)
        lines         = text.split("\n")
        in_checklist  = False
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            i += 1

            if not line:
                story.append(Spacer(1, 0.12 * cm))
                in_checklist = False
                continue

            # Garis pemisah (---, --, —) → spacer, tidak dicetak
            if re.match(r"^-{2,}$", line) or line in ("--", "—", "–"):
                story.append(Spacer(1, 0.18 * cm))
                continue

            # Artefak angka tunggal dari AI
            if re.match(r"^\d{1,2}$", line):
                continue

            # Baris hanya pipe
            if line == "|":
                continue

            # Sisa tabel terpotong ("| Siswa") → buang pipe, proses sebagai teks
            if line.startswith("|") and line.count("|") < 2:
                line = line.strip("|").strip()
                if not line:
                    continue

            # Tabel markdown
            if _is_table_row(line):
                rows, j = [], i - 1
                while j < len(lines) and _is_table_row(lines[j].strip()):
                    if not _is_sep_row(lines[j]):
                        row = _parse_row(lines[j])
                        if any(c for c in row):
                            rows.append(row)
                    j += 1
                i = j
                tbl = _md_table(rows)
                if tbl:
                    story.append(tbl)
                    story.append(Spacer(1, 0.2 * cm))
                continue

            # Header markdown (##, ###, ####)
            m = re.match(r"^(#{1,4})\s+(.*)", line)
            if m:
                level   = len(m.group(1))
                content = re.sub(r"\*\*(.*?)\*\*", r"\1", m.group(2)).strip()
                style   = S_H2 if level <= 2 else (S_H3 if level == 3 else S_H4)
                story.append(Paragraph(_clean(content), style))
                in_checklist = False
                continue

            # Blockquote markdown (> teks) → italic dengan indent
            if line.startswith(">"):
                content = line.lstrip("> ").strip()
                if content:
                    story.append(Paragraph(f"<i>{_clean(content)}</i>", S_QUOTE))
                continue

            # Placeholder gambar (**Gambar N:** atau [Gambar N])
            gm = re.match(r"^\*{0,2}[Gg]ambar\s+\d+[.:\)]\*{0,2}\s*(.*)", line)
            if not gm:
                gm = re.match(r"^\[[Gg]ambar\s+\d+\]\s*(.*)", line)
            if gm:
                cap = re.sub(r"\*\*(.*?)\*\*", r"\1", gm.group(1)).strip() or "Ilustrasi"
                story.append(_img_box(cap))
                story.append(Spacer(1, 0.15 * cm))
                continue

            # Header checklist (**Checklist:** atau Checklist:)
            if re.match(r"^\*{0,2}[Cc]hecklist[:\*\s]*$", line):
                story.append(Paragraph("<b>Checklist:</b>", S_BLABEL))
                in_checklist = True
                continue

            # Bold label berdiri sendiri: HANYA "**Label**" / "**Label:**" persis,
            # tanpa teks lain — regex ketat agar "**A** - *B*" tidak ikut tertangkap
            bl = re.match(r"^\*\*([^*]+?)(:)?\*\*\s*(:)?\s*$", line)
            if bl:
                raw       = bl.group(1).rstrip(":").strip()
                had_colon = bool(bl.group(2) or bl.group(3))
                label     = _clean(raw).strip()
                # Label kapital semua (judul bagian dari AI) → render sebagai sub-heading
                # (cek pada teks mentah, sebelum escape &amp; dll)
                if len(raw) > 3 and raw == raw.upper():
                    story.append(Paragraph(label, S_H3))
                else:
                    suffix = ":" if had_colon else ""
                    story.append(Paragraph(f"<b>{label}{suffix}</b>", S_BLABEL))
                in_checklist = "checklist" in raw.lower()
                continue

            # Bullet: dimulai dengan - atau *
            if re.match(r"^[-\*]\s+", line):
                content = re.sub(r"^[-\*]\s+", "", line)
                if in_checklist:
                    story.append(Paragraph(f"[ ] {_clean(content)}", S_CHECK))
                else:
                    story.append(Paragraph(f"&#8226; {_clean(content)}", S_BULLET))
                continue

            # Numbered list (1. 2. atau 1) 2))
            nm = re.match(r"^(\d+)[.)]\s+(.*)", line)
            if nm:
                story.append(Paragraph(
                    f"<b>{nm.group(1)}.</b>  {_clean(nm.group(2))}", S_NUM))
                in_checklist = False
                continue

            # Paragraf biasa
            story.append(Paragraph(_clean(line), S_BODY))
            in_checklist = False

    # ── Canvas callbacks ──────────────────────────────────────────────────────
    def _cover_page(canv, doc):
        # Cover hanya menggambar background full-page — TANPA footer,
        # karena cover_bg.png sudah punya ilustrasi bawah sendiri.
        canv.saveState()
        if os.path.exists(COVER_BG):
            canv.drawImage(COVER_BG, 0, 0, PW, PH,
                           preserveAspectRatio=False, mask="auto")
        canv.restoreState()

    def _content_page(canv, doc):
        canv.saveState()
        if os.path.exists(HEADER):
            canv.drawImage(HEADER, 0, PH - HEADER_H, PW, HEADER_H,
                           preserveAspectRatio=False, mask="auto")
        if os.path.exists(FOOTER):
            canv.drawImage(FOOTER, 0, 0, PW, FOOTER_H,
                           preserveAspectRatio=False, mask="auto")
        canv.setFont(FONT_N, 7)
        canv.setFillColor(C_GRAY)
        canv.drawCentredString(PW / 2, FOOTER_H / 2 - 3, f"Halaman {doc.page - 1}")
        canv.restoreState()

    # ── Page templates (cover vs konten) ──────────────────────────────────────
    # Frame cover di-inset agar konten berada DI DALAM panel putih cover_bg.png
    # (panel bg: ±13% margin kiri-kanan, mulai ±14% dari atas, berakhir ±tengah)
    COV_SIDE = 3.4 * cm                 # margin kiri/kanan konten cover
    COV_TOP  = 4.3 * cm                 # jarak dari tepi atas halaman
    COV_BOT  = 13.8 * cm                # batas bawah konten cover
    W_COV    = PW - 2 * COV_SIDE        # lebar konten cover efektif
    cover_frame   = Frame(COV_SIDE, COV_BOT,
                          W_COV, PH - COV_TOP - COV_BOT,
                          id="cover_f")
    content_frame = Frame(MARGIN, FOOTER_H + MARGIN,
                          PW - 2*MARGIN, PH - HEADER_H - FOOTER_H - 2*MARGIN,
                          id="content_f")
    cover_tpl   = PageTemplate(id="cover",   frames=[cover_frame],   onPage=_cover_page)
    content_tpl = PageTemplate(id="content", frames=[content_frame], onPage=_content_page)

    doc = BaseDocTemplate(
        filename,
        pagesize=A4,
        pageTemplates=[cover_tpl, content_tpl],
    )

    # ── Story ─────────────────────────────────────────────────────────────────
    story = []

    # ══════════════════════════════════════════════════
    # HALAMAN 1 — COVER
    # ══════════════════════════════════════════════════
    tahun_pelajaran = (
        f"{now.year} / {now.year + 1}" if now.month >= 7
        else f"{now.year - 1} / {now.year}"
    )
    gejala_cover = gejala.split(",")[0].strip()[:45]

    story.append(Spacer(1, 0.3 * cm))

    # Badge "MODUL AJAR INKLUSIF" — centered
    story.append(_PillBadge("MODUL AJAR INKLUSIF",
                            FONT_B, 8.5, C_ORANGE, C_WHITE,
                            px=14, py=6, align='CENTER', cw=W_COV))
    story.append(Spacer(1, 0.55 * cm))

    # Judul besar
    story.append(Paragraph(f"Belajar {_esc(mapel)}", S_BIG_T))
    story.append(Spacer(1, 0.3 * cm))

    # Deskripsi singkat
    story.append(Paragraph(
        f"Lembar kerja seru untuk {_esc(nama)} &mdash; "
        f"penuh panduan adaptif, kalimat pendek, "
        f"dan kegiatan menyenangkan agar makin semangat belajar!",
        S_COV_D,
    ))
    story.append(Spacer(1, 0.7 * cm))

    # Kartu identitas — latar krim, border orange
    CARD_W = min(12.5 * cm, W_COV - 0.8 * cm)
    id_rows = [
        [Paragraph("Nama Siswa",        S_ID_K), Paragraph(_esc(nama),         S_ID_V)],
        [Paragraph("Kelas",             S_ID_K), Paragraph(_esc(kelas),        S_ID_V)],
        [Paragraph("Mata Pelajaran",    S_ID_K), Paragraph(_esc(mapel),         S_ID_V)],
        [Paragraph("Kebutuhan Khusus",  S_ID_K), Paragraph(_esc(gejala_cover), S_ID_V)],
        [Paragraph("Tahun Pelajaran",   S_ID_K), Paragraph(tahun_pelajaran,    S_ID_V)],
    ]
    id_tbl = Table(id_rows,
                   colWidths=[4.2*cm, CARD_W - 4.2*cm],
                   hAlign='CENTER')
    id_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_ORANGE_L),
        ("BOX",           (0,0), (-1,-1), 1.5, C_ORANGE),
        ("INNERGRID",     (0,0), (-1,-1), 0.5, colors.HexColor("#F0D090")),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ("RIGHTPADDING",  (0,0), (-1,-1), 12),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(id_tbl)
    story.append(Spacer(1, 0.6 * cm))

    # Footer teks cover
    story.append(Paragraph(
        f"SDN / SLB Inklusif &bull; Universitas Brawijaya &bull; {now.year}",
        S_COV_FT,
    ))

    story.append(NextPageTemplate("content"))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════
    # SECTION A — Profil & Strategi Adaptasi
    # ══════════════════════════════════════════════════
    story.append(_sec_bar("A", "Profil Siswa & Strategi Adaptasi",
                          "Pegangan Guru", "Bukan untuk siswa"))
    story.append(Spacer(1, 0.2 * cm))
    _add_content(story, profiling_out or "(output profiling tidak tersedia)")

    # ══════════════════════════════════════════════════
    # SECTION B — Materi Pembelajaran Adaptif (halaman baru)
    # ══════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(_sec_bar("B", "Materi Pembelajaran Adaptif",
                          f"{_esc(mapel)} · {_esc(kelas)}",
                          f"Untuk {_esc(nama)}"))
    story.append(Spacer(1, 0.2 * cm))

    # Ilustrasi Section B: gambar 1 di awal, gambar 2 di tengah konten
    imgs = illustrations or []
    img1 = imgs[0] if len(imgs) > 0 else None
    img2 = imgs[1] if len(imgs) > 1 else None

    if img1:
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(img1, width=14*cm, height=8.75*cm, hAlign='CENTER'))
        story.append(Spacer(1, 0.4 * cm))

    content_b = adaptive_out or "(output materi adaptif tidak tersedia)"

    if img2:
        # Cari batas paragraf terdekat dengan tengah konten — hindari memotong
        # tabel markdown (blok yang diawali '|').
        blocks = content_b.split("\n\n")
        split_at = None
        if len(blocks) >= 4:
            mid = len(blocks) // 2
            for j in list(range(mid, len(blocks))) + list(range(mid - 1, 0, -1)):
                if not blocks[j].lstrip().startswith("|"):
                    split_at = j
                    break
        if split_at:
            _add_content(story, "\n\n".join(blocks[:split_at]))
            story.append(Spacer(1, 0.4 * cm))
            story.append(Image(img2, width=12*cm, height=7.5*cm, hAlign='CENTER'))
            story.append(Spacer(1, 0.4 * cm))
            _add_content(story, "\n\n".join(blocks[split_at:]))
        else:
            _add_content(story, content_b)
            story.append(Spacer(1, 0.5 * cm))
            story.append(Image(img2, width=12*cm, height=7.5*cm, hAlign='CENTER'))
    else:
        _add_content(story, content_b)

    # Section C tidak dicetak — tersedia di API response & 03_Laporan_Audit.md

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

    # Generate ilustrasi Section B via Groq + Pollinations
    print("\n  Membuat ilustrasi untuk Section B...")
    img_prompts = _fetch_image_prompts(
        data["mata_pelajaran"], data["kelas"], data["gejala"]
    )
    illustrations = []
    for i, prompt in enumerate(img_prompts, 1):
        print(f"  [{i}/{len(img_prompts)}] {prompt[:70]}...")
        path = _generate_illustration(prompt)
        if path:
            illustrations.append(path)
            print(f"  OK: {os.path.basename(path)}")
        else:
            print(f"  SKIP: gagal download (PDF tetap dibuat)")

    pdf_file = generate_pdf(data, profiling_out, adaptive_out, insight_out, output_dir,
                            illustrations=illustrations)

    tampilkan_hasil(hasil, output_dir)
    print(f"📄 PDF  : {pdf_file}")
    print(f"📂 Folder: {output_dir}/")
    print()


if __name__ == "__main__":
    main()
