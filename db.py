import logging
from psycopg2.pool import SimpleConnectionPool
from pgvector.psycopg2 import register_vector

from config import Config

logger = logging.getLogger("docqa.db")

_pool = None


def get_pool():
    """Lazily creates the connection pool — avoids connecting at import time,
    which matters for tests and for fast, clean startup failures."""
    global _pool
    if _pool is None:
        if not Config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = SimpleConnectionPool(1, 10, Config.DATABASE_URL)
    return _pool


def get_conn():
    conn = get_pool().getconn()
    register_vector(conn)
    return conn


def _get_bootstrap_conn():
    """A connection that skips register_vector — used only for the very first
    setup step, since the vector type doesn't exist in a fresh database until
    CREATE EXTENSION has run. Every other caller should use get_conn()."""
    return get_pool().getconn()


def put_conn(conn):
    get_pool().putconn(conn)


def init_db():
    """Creates the pgvector extension and schema if they don't exist yet.
    Safe to call on every startup."""
    conn = _get_bootstrap_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    source TEXT NOT NULL,
                    chunk_index INT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector(384),
                    created_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_chunks_tenant "
                "ON document_chunks (tenant_id);"
            )
        conn.commit()
        logger.info("Database schema ready")
    finally:
        put_conn(conn)


def insert_chunks(tenant_id, source, chunks, embeddings):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                cur.execute(
                    """
                    INSERT INTO document_chunks
                        (tenant_id, source, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (tenant_id, source, i, chunk, embedding),
                )
        conn.commit()
    finally:
        put_conn(conn)


def search_chunks(tenant_id, query_embedding, top_k=5):
    """Cosine-distance nearest neighbor search, scoped to one tenant."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, source
                FROM document_chunks
                WHERE tenant_id = %s
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (tenant_id, query_embedding, top_k),
            )
            return cur.fetchall()
    finally:
        put_conn(conn)


def reset_tenant(tenant_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM document_chunks WHERE tenant_id = %s", (tenant_id,))
        conn.commit()
    finally:
        put_conn(conn)
