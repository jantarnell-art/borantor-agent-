import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH

logger = logging.getLogger(__name__)


def init_db():
    with _conn() as conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS articles (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                url           TEXT NOT NULL UNIQUE,
                kalla         TEXT NOT NULL,
                rubrik        TEXT,
                artikel_datum DATE,
                processed_at  DATETIME NOT NULL,
                raw_text      TEXT
            );

            CREATE TABLE IF NOT EXISTS affarer (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                artikel_id          INTEGER NOT NULL REFERENCES articles(id),
                artikel_url         TEXT NOT NULL,
                kalla               TEXT NOT NULL,
                artikel_rubrik      TEXT,
                artikel_datum       DATE,
                extracted_at        DATETIME NOT NULL,
                kopare              TEXT,
                saljare             TEXT,
                fastighetstyp       TEXT,
                adress              TEXT,
                ort                 TEXT,
                region              TEXT,
                kope_datum          DATE,
                kopeskilling_msek   REAL,
                loa_kvm             INTEGER,
                boa_kvm             INTEGER,
                kr_per_kvm          INTEGER,
                da_krav_pct         REAL,
                uthyrningsgrad_pct  REAL,
                beskrivning         TEXT,
                confidence          TEXT,
                raw_text            TEXT
            );

            CREATE INDEX IF NOT EXISTS ix_affarer_datum  ON affarer(kope_datum);
            CREATE INDEX IF NOT EXISTS ix_affarer_kalla  ON affarer(kalla);
            CREATE INDEX IF NOT EXISTS ix_affarer_typ    ON affarer(fastighetstyp);
            CREATE INDEX IF NOT EXISTS ix_affarer_ort    ON affarer(ort);
            CREATE INDEX IF NOT EXISTS ix_affarer_kopare ON affarer(kopare);
        """)
    logger.info(f"Databas: {DB_PATH}")


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def article_already_processed(url: str) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()
        return row is not None


def save_article(url, kalla, rubrik, artikel_datum, raw_text) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO articles (url, kalla, rubrik, artikel_datum, processed_at, raw_text) VALUES (?,?,?,?,?,?)",
            (url, kalla, rubrik, artikel_datum, datetime.now().isoformat(), raw_text),
        )
        if cur.lastrowid:
            return cur.lastrowid
        return conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()["id"]


def save_deal(artikel_id: int, deal) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO affarer (
                artikel_id, artikel_url, kalla, artikel_rubrik, artikel_datum, extracted_at,
                kopare, saljare, fastighetstyp, adress, ort, region, kope_datum,
                kopeskilling_msek, loa_kvm, boa_kvm, kr_per_kvm,
                da_krav_pct, uthyrningsgrad_pct, beskrivning, confidence, raw_text
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                artikel_id, deal.artikel_url, deal.kalla, deal.artikel_rubrik,
                deal.artikel_datum, datetime.now().isoformat(),
                deal.kopare, deal.saljare, deal.fastighetstyp,
                deal.adress, deal.ort, deal.region, deal.kope_datum,
                deal.kopeskilling_msek, deal.loa_kvm, deal.boa_kvm, deal.kr_per_kvm,
                deal.da_krav_pct, deal.uthyrningsgrad_pct, deal.beskrivning,
                deal.confidence, deal.raw_text,
            ),
        )
        return cur.lastrowid


def get_recent_deals(days: int = 30) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM affarer WHERE extracted_at >= datetime('now', ? || ' days') ORDER BY extracted_at DESC",
            (f"-{days}",),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_deals() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM affarer ORDER BY extracted_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_deal_stats() -> dict:
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM affarer").fetchone()[0]
        by_type = conn.execute(
            """SELECT fastighetstyp, COUNT(*) as n,
                      AVG(kopeskilling_msek) as avg_pris,
                      AVG(kr_per_kvm) as avg_kvm
               FROM affarer WHERE fastighetstyp IS NOT NULL
               GROUP BY fastighetstyp ORDER BY n DESC"""
        ).fetchall()
        by_source = conn.execute(
            "SELECT kalla, COUNT(*) as n FROM affarer GROUP BY kalla ORDER BY n DESC"
        ).fetchall()
        top_buyers = conn.execute(
            """SELECT kopare, COUNT(*) as n, SUM(kopeskilling_msek) as total_msek
               FROM affarer WHERE kopare IS NOT NULL
               GROUP BY kopare ORDER BY n DESC LIMIT 20"""
        ).fetchall()
        top_sellers = conn.execute(
            """SELECT saljare, COUNT(*) as n, SUM(kopeskilling_msek) as total_msek
               FROM affarer WHERE saljare IS NOT NULL
               GROUP BY saljare ORDER BY n DESC LIMIT 20"""
        ).fetchall()
        volume_by_month = conn.execute(
            """SELECT strftime('%Y-%m', COALESCE(kope_datum, artikel_datum, extracted_at)) as manad,
                      COUNT(*) as n, SUM(kopeskilling_msek) as total_msek
               FROM affarer
               GROUP BY manad ORDER BY manad DESC LIMIT 24"""
        ).fetchall()
        return {
            "total": total,
            "by_type": [dict(r) for r in by_type],
            "by_source": [dict(r) for r in by_source],
            "top_buyers": [dict(r) for r in top_buyers],
            "top_sellers": [dict(r) for r in top_sellers],
            "volume_by_month": [dict(r) for r in volume_by_month],
        }
