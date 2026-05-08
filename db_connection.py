import os
import psycopg2
import redis as redis_lib
from dotenv import load_dotenv

load_dotenv(override=True)


# ── Redis — coba konek saat modul diimport ───────────────────────────────────
# socket_connect_timeout: batas waktu handshake TCP (detik)
# socket_timeout: batas waktu tiap operasi read/write (detik)

REDIS_ENABLED: bool = False
redis_client: redis_lib.Redis | None = None

try:
    _client = redis_lib.Redis(
        host=os.getenv("REDIS_HOST"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    _client.ping()
    redis_client = _client
    REDIS_ENABLED = True
    print("✅ Redis ElastiCache terhubung. Cache aktif.")
except Exception as e:
    print(f"⚠️ Redis tidak tersedia ({type(e).__name__}: {e}). Cache dinonaktifkan, sistem tetap berjalan.")


# ── PostgreSQL ────────────────────────────────────────────────────────────────

def get_postgres_connection() -> psycopg2.extensions.connection:
    """Buat koneksi ke RDS PostgreSQL. Pastikan .env berisi DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=int(os.getenv("DB_PORT", 5432)),
    )


def get_redis_client() -> redis_lib.Redis | None:
    """Return Redis client aktif, atau None jika tidak tersedia (REDIS_ENABLED=False)."""
    return redis_client


# ── Test koneksi ──────────────────────────────────────────────────────────────

def test_connections():
    print("=" * 50)
    print("🔌 Tes Koneksi ASIQ Infrastructure")
    print("=" * 50)

    print("\n📦 Menguji koneksi ke RDS PostgreSQL...")
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print("✅ PostgreSQL terhubung!")
        print(f"   Versi: {version[0][:60]}...")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ PostgreSQL gagal terhubung: {e}")

    print("\n⚡ Menguji koneksi ke Redis ElastiCache...")
    if REDIS_ENABLED:
        print("✅ Redis terhubung (REDIS_ENABLED=True)")
        print(f"   Host: {os.getenv('REDIS_HOST')}")
    else:
        print("⚠️ Redis tidak tersedia (REDIS_ENABLED=False)")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    test_connections()
