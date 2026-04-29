"""DB スキーマ初期化 + マイグレーション適用"""
import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "/data/stocks.db")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run_migrations() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}

    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_file.name in applied:
            continue
        print(f"Applying {sql_file.name} ...")
        conn.executescript(sql_file.read_text())
        conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", [sql_file.name])
        conn.commit()
        print(f"  Done.")

    conn.close()
    print("All migrations applied.")


if __name__ == "__main__":
    run_migrations()
