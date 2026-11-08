"""Business catalog: maps project codes to the vocabulary business users know.

The CSV lives at src/api/config/catalog.csv (override with the
LINEAGE_CATALOG environment variable). Columns:
project, value_chain, source_system, target_system, tables
where tables is a '|'-separated whitelist of the tables shown in the business view.
"""
import csv
import os
import threading
from pathlib import Path
from typing import Any

ENV_CATALOG = "LINEAGE_CATALOG"
DEFAULT_CATALOG = Path(__file__).resolve().parents[3] / "src" / "api" / "config" / "catalog.csv"


class BusinessCatalog:
    """Project name -> business mapping; re-reads the CSV when it changes on disk."""

    def __init__(self, path: str | Path | None = None) -> None:
        env = os.environ.get(ENV_CATALOG)
        self.path = Path(path or env or DEFAULT_CATALOG).expanduser()
        self._lock = threading.Lock()
        self._cache: tuple[tuple, dict[str, dict[str, Any]]] | None = None

    def entries(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            try:
                st = self.path.stat()
                stamp = (st.st_mtime_ns, st.st_size)
            except OSError:
                self._cache = None
                return {}
            if self._cache is None or self._cache[0] != stamp:
                self._cache = (stamp, self._read())
            return self._cache[1]

    def _read(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        with self.path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                project = (row.get("project") or "").strip()
                if not project:
                    continue
                out[project] = {
                    "value_chain": (row.get("value_chain") or "").strip() or None,
                    "source_system": (row.get("source_system") or "").strip() or None,
                    "target_system": (row.get("target_system") or "").strip() or None,
                    "business_tables": [
                        t.strip() for t in (row.get("tables") or "").split("|") if t.strip()
                    ],
                    # Position in the CSV; the UI preselects the filters of the first row.
                    "catalog_order": len(out),
                }
        return out
