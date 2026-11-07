import os
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_business_catalog(monkeypatch):
    """Keep tests independent of the real src/ui/config/catalog.csv."""
    monkeypatch.setenv("LINEAGE_CATALOG", "/nonexistent/catalog.csv")


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "outputs" / "SP_CLO" / "lineage.db"


@pytest.fixture(scope="session")
def lineage_db_path() -> Path:
    path = Path(os.environ.get("LINEAGE_DB", DEFAULT_DB))
    if not path.exists():
        pytest.skip(f"lineage DB not found: {path}")
    return path


@pytest.fixture(scope="session")
def conn(lineage_db_path):
    uri = f"file:{lineage_db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()
