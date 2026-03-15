import os
import json
import logging
from typing import Optional
from models import Insight, Anomaly
from datetime import datetime, timezone

log = logging.getLogger("overwatch.database")

DATABASE_URL = os.getenv("DATABASE_URL", "")

_conn = None


def _get_conn():
    global _conn
    import psycopg2
    import psycopg2.extras
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(DATABASE_URL)
    return _conn


def init_db():
    if not DATABASE_URL:
        log.info("DATABASE_URL not set — running without persistence")
        return
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS overwatch_insights (
                    id          SERIAL PRIMARY KEY,
                    collected_at TIMESTAMPTZ NOT NULL,
                    status      TEXT NOT NULL,
                    summary     TEXT NOT NULL,
                    anomalies   JSONB NOT NULL DEFAULT '[]',
                    recommendations JSONB NOT NULL DEFAULT '[]'
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_insights_time
                ON overwatch_insights (collected_at DESC)
            """)
        conn.commit()
        log.info("Database initialized")
    except Exception as e:
        log.error("Database init failed: %s", e)


def save_insight(insight: Insight):
    if not DATABASE_URL:
        return
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO overwatch_insights
                   (collected_at, status, summary, anomalies, recommendations)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    insight.collected_at,
                    insight.status,
                    insight.summary,
                    json.dumps([a.model_dump() for a in insight.anomalies]),
                    json.dumps(insight.recommendations),
                ),
            )
            # Keep last 200 records
            cur.execute("""
                DELETE FROM overwatch_insights
                WHERE id NOT IN (
                    SELECT id FROM overwatch_insights
                    ORDER BY collected_at DESC LIMIT 200
                )
            """)
        conn.commit()
    except Exception as e:
        log.error("Failed to save insight: %s", e)
        global _conn
        _conn = None  # force reconnect next time


def load_latest() -> Optional[Insight]:
    if not DATABASE_URL:
        return None
    try:
        import psycopg2.extras
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT * FROM overwatch_insights
                ORDER BY collected_at DESC LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                return None
            return Insight(
                id=row["id"],
                collected_at=row["collected_at"],
                status=row["status"],
                summary=row["summary"],
                anomalies=[Anomaly(**a) for a in row["anomalies"]],
                recommendations=row["recommendations"],
            )
    except Exception as e:
        log.error("Failed to load latest insight: %s", e)
        return None


def load_history(limit: int = 48) -> list[Insight]:
    if not DATABASE_URL:
        return []
    try:
        import psycopg2.extras
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT * FROM overwatch_insights
                   ORDER BY collected_at DESC LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
            return [
                Insight(
                    id=r["id"],
                    collected_at=r["collected_at"],
                    status=r["status"],
                    summary=r["summary"],
                    anomalies=[Anomaly(**a) for a in r["anomalies"]],
                    recommendations=r["recommendations"],
                )
                for r in rows
            ]
    except Exception as e:
        log.error("Failed to load history: %s", e)
        return []
