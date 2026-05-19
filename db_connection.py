import logging
import os
import time
from typing import Optional

import psycopg2
import psycopg2.pool
import redis as redis_lib
from dotenv import load_dotenv

load_dotenv(override=True)

log = logging.getLogger("asiq.db")

# ── Redis — konek saat modul diimport, retry sekali jika gagal ───────────────

REDIS_ENABLED: bool = False
redis_client: Optional[redis_lib.Redis] = None

_REDIS_RETRIES = 2
_REDIS_TIMEOUT = 3  # detik


def _init_redis() -> tuple[bool, Optional[redis_lib.Redis]]:
    host = os.getenv("REDIS_HOST")
    if not host:
        log.info("REDIS_HOST tidak di-set. Cache dinonaktifkan.")
        return False, None

    for attempt in range(1, _REDIS_RETRIES + 1):
        try:
            client = redis_lib.Redis(
                host=host,
                port=int(os.getenv("REDIS_PORT", 6379)),
                decode_responses=True,
                socket_connect_timeout=_REDIS_TIMEOUT,
                socket_timeout=_REDIS_TIMEOUT,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            client.ping()
            log.info("Redis terhubung di %s:%s", host, os.getenv("REDIS_PORT", 6379))
            return True, client
        except Exception as e:
            if attempt < _REDIS_RETRIES:
                log.warning("Redis gagal (attempt %d/%d): %s — retry...", attempt, _REDIS_RETRIES, e)
                time.sleep(1)
            else:
                log.warning("Redis tidak tersedia: %s. Cache dinonaktifkan, sistem tetap berjalan.", e)
    return False, None


REDIS_ENABLED, redis_client = _init_redis()


# ── PostgreSQL Connection Pool ────────────────────────────────────────────────
# Pool mencegah overhead buka/tutup koneksi setiap request.

_pg_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

_PG_POOL_MIN = int(os.getenv("DB_POOL_MIN", 1))
_PG_POOL_MAX = int(os.getenv("DB_POOL_MAX", 5))
_PG_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", 5))


def _pg_dsn() -> dict:
    return dict(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=int(os.getenv("DB_PORT", 5432)),
        connect_timeout=_PG_CONNECT_TIMEOUT,
    )


def _init_pg_pool() -> Optional[psycopg2.pool.ThreadedConnectionPool]:
    dsn = _pg_dsn()
    if not dsn.get("host"):
        log.info("DB_HOST tidak di-set. PostgreSQL dinonaktifkan.")
        return None
    try:
        pool = psycopg2.pool.ThreadedConnectionPool(_PG_POOL_MIN, _PG_POOL_MAX, **dsn)
        log.info("PostgreSQL connection pool siap (min=%d max=%d)", _PG_POOL_MIN, _PG_POOL_MAX)
        return pool
    except Exception as e:
        log.warning("PostgreSQL pool gagal dibuat: %s", e)
        return None


_pg_pool = _init_pg_pool()


def get_postgres_connection() -> psycopg2.extensions.connection:
    """
    Ambil koneksi dari pool jika tersedia, fallback ke koneksi baru.
    Kalau pool penuh atau tidak tersedia, coba langsung.
    """
    if _pg_pool is not None:
        try:
            conn = _pg_pool.getconn()
            # Kembalikan ke pool setelah selesai — caller wajib panggil pool.putconn()
            # atau pakai context manager _pg_conn() di bawah.
            return conn
        except Exception:
            pass
    # Fallback: koneksi langsung
    return psycopg2.connect(**_pg_dsn())


def release_postgres_connection(conn: psycopg2.extensions.connection) -> None:
    """Kembalikan koneksi ke pool. Panggil setelah selesai pakai get_postgres_connection()."""
    if _pg_pool is not None:
        try:
            _pg_pool.putconn(conn)
            return
        except Exception:
            pass
    try:
        conn.close()
    except Exception:
        pass


def get_redis_client() -> Optional[redis_lib.Redis]:
    """Return Redis client aktif, atau None jika tidak tersedia."""
    return redis_client


# ── Test koneksi (dipakai oleh setup/debug) ───────────────────────────────────

def test_connections():
    print("=" * 50)
    print("Tes Koneksi ASIQ Infrastructure")
    print("=" * 50)

    print("\nMenguji koneksi ke RDS PostgreSQL...")
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print(f"PostgreSQL terhubung! Versi: {version[0][:60]}...")
        cursor.close()
        release_postgres_connection(conn)
    except Exception as e:
        print(f"PostgreSQL gagal: {e}")

    print("\nMenguji koneksi ke Redis ElastiCache...")
    if REDIS_ENABLED and redis_client:
        info = redis_client.info("server")
        print(f"Redis terhubung! Versi: {info.get('redis_version', 'N/A')}")
        print(f"Host: {os.getenv('REDIS_HOST')}")
    else:
        print("Redis tidak tersedia (REDIS_ENABLED=False)")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_connections()
