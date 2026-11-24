import sqlite3
from pathlib import Path
from contextlib import contextmanager
from .config import settings

def db_path():
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise RuntimeError("This MVP build uses SQLite. PostgreSQL adapter is a V2 migration.")
    path = Path(url.replace("sqlite:///", "", 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            category TEXT NOT NULL,
            style TEXT NOT NULL,
            duration INTEGER NOT NULL,
            platforms TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            script TEXT DEFAULT '',
            output_path TEXT DEFAULT '',
            quality_score INTEGER DEFAULT 0,
            quality_notes TEXT DEFAULT '',
            publish_status TEXT DEFAULT 'not_started',
            error TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
