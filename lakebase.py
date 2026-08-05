"""
Lakebase (Databricks-managed Postgres) connection helper.

Connects using a single LAKEBASE_URL (a standard Postgres connection URL,
e.g. postgresql://role:password@host:5432/databricks_postgres?sslmode=require)
pointing at a native Postgres role with a static, non-expiring password.
This keeps setup to a single secret instead of five separate env vars.
"""

import base64
import logging
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from sqlalchemy import create_engine

try:
    from databricks.sdk import WorkspaceClient
    _w = WorkspaceClient()
except Exception:
    _w = None

logger = logging.getLogger("lakebase")

_SCOPE = os.environ.get("LAKEBASE_SECRET_SCOPE", "database")
_KEY = os.environ.get("LAKEBASE_SECRET_KEY", "lakebase-url")


def _lakebase_url() -> str:
    """Fetch and decode the Lakebase connection URL from environment or Databricks secret scope."""
    env_url = os.environ.get("LAKEBASE_URL")
    if env_url:
        return env_url
    if _w is not None:
        secret = _w.secrets.get_secret(scope=_SCOPE, key=_KEY)
        return base64.b64decode(secret.value).decode("utf-8")
    raise RuntimeError("LAKEBASE_URL environment variable is not set and Databricks SDK is unavailable.")


@contextmanager
def get_connection():
    """Yield a raw psycopg2 connection with a RealDictCursor factory."""
    conn = psycopg2.connect(_lakebase_url(), cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


def get_engine():
    """Return a SQLAlchemy engine for Lakebase."""
    return create_engine(_lakebase_url())


def run_query(sql: str, params: tuple | dict | None = None) -> list[dict]:
    """Run a read query against Lakebase and return rows as list[dict]."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def run_write(sql: str, params: tuple | dict | None = None) -> int:
    """Run an INSERT/UPDATE/DELETE against Lakebase, return affected row count."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.rowcount


def init_db():
    """Create tickets and ticket_messages tables if they don't exist, and seed initial data if empty."""
    create_tickets_sql = """
    CREATE TABLE IF NOT EXISTS tickets (
        ticket_id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        priority TEXT NOT NULL DEFAULT 'medium',
        category TEXT NOT NULL DEFAULT 'general',
        created_by TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    create_messages_sql = """
    CREATE TABLE IF NOT EXISTS ticket_messages (
        message_id SERIAL PRIMARY KEY,
        ticket_id INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
        message_text TEXT NOT NULL,
        author TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(create_tickets_sql)
            cur.execute(create_messages_sql)
            conn.commit()

            cur.execute("SELECT COUNT(*) AS count FROM tickets;")
            res = cur.fetchone()
            count = res["count"] if res else 0

            if count == 0:
                logger.info("Tickets table is empty. Seeding initial support tickets & messages...")
                _seed_data(cur, conn)


def _seed_data(cur, conn):
    sample_tickets = [
        {
            "title": "Unable to access Databricks Lakehouse SQL warehouse",
            "status": "open",
            "priority": "high",
            "category": "technical",
            "created_by": "alice.engineer@company.com",
            "messages": [
                (
                    "Hi team, I am getting a permission denied error when trying to run queries on the main SQL warehouse.",
                    "alice.engineer@company.com",
                ),
                (
                    "Thanks for reporting this Alice! We are checking your workspace IAM roles.",
                    "support.hero@company.com",
                ),
            ],
        },
        {
            "title": "Monthly billing invoice discrepancy for July",
            "status": "in_progress",
            "priority": "medium",
            "category": "billing",
            "created_by": "bob.manager@company.com",
            "messages": [
                (
                    "The DBU usage on our latest invoice seems higher than our allocated quota. Could you review?",
                    "bob.manager@company.com",
                ),
                (
                    "Hello Bob, our finance ops team is auditing the DBU logs for July. Will update shortly.",
                    "billing.team@company.com",
                ),
                (
                    "Attached the breakdown for cluster compute vs serverless SQL.",
                    "billing.team@company.com",
                ),
            ],
        },
        {
            "title": "Dashboard UI rendering glitch on Firefox mobile",
            "status": "resolved",
            "priority": "low",
            "category": "bug",
            "created_by": "carol.design@company.com",
            "messages": [
                (
                    "Filter dropdowns overlap with header elements when viewed on screens smaller than 768px.",
                    "carol.design@company.com",
                ),
                (
                    "Fixed in v1.4.2 deployment. Please hard refresh your browser.",
                    "dev.team@company.com",
                ),
                (
                    "Verified fixed, thanks!",
                    "carol.design@company.com",
                ),
            ],
        },
    ]
    for t in sample_tickets:
        cur.execute(
            """
            INSERT INTO tickets (title, status, priority, category, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING ticket_id;
            """,
            (t["title"], t["status"], t["priority"], t["category"], t["created_by"]),
        )
        ticket_id = cur.fetchone()["ticket_id"]
        for msg_text, author in t["messages"]:
            cur.execute(
                """
                INSERT INTO ticket_messages (ticket_id, message_text, author)
                VALUES (%s, %s, %s);
                """,
                (ticket_id, msg_text, author),
            )
    conn.commit()
