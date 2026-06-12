"""SQLite database layer - all writes are append-only; no historical data is overwritten."""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import date, datetime
from typing import Optional

from config import DB_PATH

logger = logging.getLogger(__name__)


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    """Create all tables if they don't exist."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS list_rates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                collected_at DATETIME NOT NULL,
                rate_date   DATE NOT NULL,
                bank        TEXT NOT NULL,
                period_key  TEXT NOT NULL,
                period_label TEXT NOT NULL,
                rate        REAL NOT NULL,
                source_url  TEXT,
                UNIQUE(rate_date, bank, period_key)
            );

            CREATE TABLE IF NOT EXISTS avg_rates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                collected_at DATETIME NOT NULL,
                rate_date   DATE NOT NULL,
                bank        TEXT NOT NULL,
                period_key  TEXT NOT NULL,
                period_label TEXT NOT NULL,
                rate        REAL NOT NULL,
                source_url  TEXT,
                UNIQUE(rate_date, bank, period_key)
            );

            CREATE TABLE IF NOT EXISTS reference_rates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                collected_at DATETIME NOT NULL,
                rate_date   DATE NOT NULL,
                series_key  TEXT NOT NULL,
                series_label TEXT NOT NULL,
                rate        REAL NOT NULL,
                source      TEXT,
                UNIQUE(rate_date, series_key)
            );

            CREATE TABLE IF NOT EXISTS my_offers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  DATETIME NOT NULL,
                offer_date  DATE NOT NULL,
                bank        TEXT NOT NULL,
                period_key  TEXT NOT NULL,
                period_label TEXT NOT NULL,
                offered_rate REAL NOT NULL,
                loan_amount INTEGER,
                discount_vs_list REAL,
                comment     TEXT,
                source      TEXT
            );

            CREATE TABLE IF NOT EXISTS warnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  DATETIME NOT NULL,
                warning_date DATE NOT NULL,
                category    TEXT NOT NULL,
                bank        TEXT,
                period_key  TEXT,
                message     TEXT NOT NULL,
                severity    TEXT NOT NULL DEFAULT 'INFO',
                acknowledged INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS ix_list_rates_date_bank
                ON list_rates(rate_date, bank);
            CREATE INDEX IF NOT EXISTS ix_ref_rates_date
                ON reference_rates(rate_date, series_key);
            CREATE INDEX IF NOT EXISTS ix_my_offers_date
                ON my_offers(offer_date, bank);
            CREATE INDEX IF NOT EXISTS ix_warnings_date
                ON warnings(warning_date);
        """)
    logger.info("Database initialized at %s", DB_PATH)


# ---------- List rates ----------

def upsert_list_rate(
    rate_date: date,
    bank: str,
    period_key: str,
    period_label: str,
    rate: float,
    source_url: Optional[str] = None,
) -> None:
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO list_rates
                (collected_at, rate_date, bank, period_key, period_label, rate, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rate_date, bank, period_key)
            DO UPDATE SET rate=excluded.rate,
                          collected_at=excluded.collected_at,
                          source_url=excluded.source_url
            """,
            (now, rate_date.isoformat(), bank, period_key, period_label, rate, source_url),
        )


def get_list_rates(bank: Optional[str] = None, limit: int = 500):
    with _conn() as con:
        if bank:
            rows = con.execute(
                "SELECT * FROM list_rates WHERE bank=? ORDER BY rate_date DESC, period_key LIMIT ?",
                (bank, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM list_rates ORDER BY rate_date DESC, bank, period_key LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_latest_list_rates():
    """Return the most recent rate for every bank+period combination."""
    with _conn() as con:
        rows = con.execute("""
            SELECT lr.*
            FROM list_rates lr
            INNER JOIN (
                SELECT bank, period_key, MAX(rate_date) AS max_date
                FROM list_rates
                GROUP BY bank, period_key
            ) latest
            ON lr.bank = latest.bank
               AND lr.period_key = latest.period_key
               AND lr.rate_date = latest.max_date
            ORDER BY lr.bank, lr.period_key
        """).fetchall()
    return [dict(r) for r in rows]


# ---------- Average rates ----------

def upsert_avg_rate(
    rate_date: date,
    bank: str,
    period_key: str,
    period_label: str,
    rate: float,
    source_url: Optional[str] = None,
) -> None:
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO avg_rates
                (collected_at, rate_date, bank, period_key, period_label, rate, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rate_date, bank, period_key)
            DO UPDATE SET rate=excluded.rate,
                          collected_at=excluded.collected_at,
                          source_url=excluded.source_url
            """,
            (now, rate_date.isoformat(), bank, period_key, period_label, rate, source_url),
        )


# ---------- Reference rates ----------

def upsert_reference_rate(
    rate_date: date,
    series_key: str,
    series_label: str,
    rate: float,
    source: Optional[str] = None,
) -> None:
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO reference_rates
                (collected_at, rate_date, series_key, series_label, rate, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(rate_date, series_key)
            DO UPDATE SET rate=excluded.rate,
                          collected_at=excluded.collected_at,
                          source=excluded.source
            """,
            (now, rate_date.isoformat(), series_key, series_label, rate, source),
        )


def get_latest_reference_rates():
    with _conn() as con:
        rows = con.execute("""
            SELECT rr.*
            FROM reference_rates rr
            INNER JOIN (
                SELECT series_key, MAX(rate_date) AS max_date
                FROM reference_rates
                GROUP BY series_key
            ) latest
            ON rr.series_key = latest.series_key
               AND rr.rate_date = latest.max_date
            ORDER BY rr.series_key
        """).fetchall()
    return [dict(r) for r in rows]


def get_reference_rate_history(series_key: str, days: int = 365):
    with _conn() as con:
        rows = con.execute(
            """
            SELECT * FROM reference_rates
            WHERE series_key=?
              AND rate_date >= date('now', ? || ' days')
            ORDER BY rate_date
            """,
            (series_key, f"-{days}"),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- My offers ----------

def insert_my_offer(
    offer_date: date,
    bank: str,
    period_key: str,
    period_label: str,
    offered_rate: float,
    loan_amount: Optional[int] = None,
    discount_vs_list: Optional[float] = None,
    comment: Optional[str] = None,
    source: Optional[str] = None,
) -> int:
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO my_offers
                (created_at, offer_date, bank, period_key, period_label,
                 offered_rate, loan_amount, discount_vs_list, comment, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now, offer_date.isoformat(), bank, period_key, period_label,
                offered_rate, loan_amount, discount_vs_list, comment, source,
            ),
        )
        return cur.lastrowid


def get_my_offers(bank: Optional[str] = None):
    with _conn() as con:
        if bank:
            rows = con.execute(
                "SELECT * FROM my_offers WHERE bank=? ORDER BY offer_date DESC",
                (bank,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM my_offers ORDER BY offer_date DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_latest_my_offer(bank: str, period_key: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            """
            SELECT * FROM my_offers
            WHERE bank=? AND period_key=?
            ORDER BY offer_date DESC LIMIT 1
            """,
            (bank, period_key),
        ).fetchone()
    return dict(row) if row else None


# ---------- Warnings ----------

def insert_warning(
    warning_date: date,
    category: str,
    message: str,
    severity: str = "WARNING",
    bank: Optional[str] = None,
    period_key: Optional[str] = None,
) -> None:
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO warnings
                (created_at, warning_date, category, bank, period_key, message, severity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now, warning_date.isoformat(), category, bank, period_key, message, severity),
        )


def get_warnings(acknowledged: bool = False, limit: int = 100):
    with _conn() as con:
        rows = con.execute(
            """
            SELECT * FROM warnings
            WHERE acknowledged=?
            ORDER BY warning_date DESC, created_at DESC
            LIMIT ?
            """,
            (1 if acknowledged else 0, limit),
        ).fetchall()
    return [dict(r) for r in rows]
