import os
import sqlite3
from contextlib import contextmanager
from datetime import date

DB_PATH = os.environ.get("DB_PATH", "../data/stocks.db")


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_last_updated() -> date | None:
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT MAX(created_at) FROM financials").fetchone()
            if row and row[0]:
                return date.fromisoformat(row[0][:10])
    except Exception:
        pass
    return None


def db_exists() -> bool:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1 FROM companies LIMIT 1")
        return True
    except Exception:
        return False
