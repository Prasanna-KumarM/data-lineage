"""Create and fill the lineage database transactionally."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from par_fpl_lineage.db.schema import TABLES


def create_database(path: Path) -> sqlite3.Connection:
    """A fresh database at path with the full lineage schema. Not commited; the caller owns the transaction."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        for ddl in TABLES:
            conn.execute(ddl)
    except Exception:
        conn.close()
        path.unlink(missing_ok=True)
        raise
    return conn
