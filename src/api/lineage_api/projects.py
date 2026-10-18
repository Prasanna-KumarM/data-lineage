"""Finds the project databases under an outputs folder: <outputs>/<folder>/lineage.db, one per project."""
import sqlite3
import threading
from pathlib import Path
from typing import Any

from lineage_api.catalog import list_projects
from lineage_api.db import DatabaseUnavailable, SchemaMismatch, check_schema, open_readonly

ENV_OUTPUTS_DIR = "LINEAGE_OUTPUTS_DIR"
DB_FILE_NAME = "lineage.db"


class ProjectRegistry:
    """Lists the databases that exist right now and maps each project name to its file.

    The folders are looked at on every call so a database added later appears without a restart;
    the content of a database is only re-read when its file changes."""

    def __init__(self, outputs_dir: str | Path) -> None:
        self.outputs_dir = Path(outputs_dir).expanduser()
        self._cache: dict[Path, tuple[tuple, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    def _files(self) -> list[Path]:
        if not self.outputs_dir.is_dir():
            return []
        return sorted(p for p in self.outputs_dir.glob(f"*/{DB_FILE_NAME}") if p.is_file())

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        folder = path.parent.name
        try:
            conn = open_readonly(path)
        except DatabaseUnavailable:
            return [{"project_name": folder, "folder": folder, "path": path, "ready": False,
                     "problem": "The database file cannot be opened."}]
        try:
            check_schema(conn)
            names = list_projects(conn)
        except SchemaMismatch:
            return [{"project_name": folder, "folder": folder, "path": path, "ready": False,
                     "problem": "The database needs to be migrated (run ./start.sh --migrate)."}]
        except (DatabaseUnavailable, sqlite3.Error):
            return [{"project_name": folder, "folder": folder, "path": path, "ready": False,
                     "problem": "The database could not be read."}]
        finally:
            conn.close()
        if not names:
            return [{"project_name": folder, "folder": folder, "path": path, "ready": False,
                     "problem": "The database has no lineage."}]
        return [{"project_name": n, "folder": folder, "path": path, "ready": True, "problem": None} for n in names]

    def entries(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        owner: dict[str, str] = {}
        with self._lock:
            files = self._files()
            for stale in set(self._cache) - set(files):
                del self._cache[stale]
            for path in files:
                st = path.stat()
                stamp = (st.st_mtime_ns, st.st_size)
                cached = self._cache.get(path)
                if cached is None or cached[0] != stamp:
                    cached = (stamp, self._read(path))
                    self._cache[path] = cached
                for entry in cached[1]:
                    name = entry["project_name"]
                    if name in owner:
                        # The first folder (alphabetically) keeps a name used twice; show the other one as unusable.
                        if entry["folder"] == name or entry["folder"] in owner:
                            continue
                        entry = {**entry, "project_name": entry["folder"], "ready": False,
                                 "problem": f"Its database also reports the project name {name}, already used by the folder {owner[name]}."}
                        name = entry["project_name"]
                    owner[name] = entry["folder"]
                    out.append(entry)
        return sorted(out, key=lambda e: e["project_name"])

    def find(self, project: str) -> dict[str, Any] | None:
        return next((e for e in self.entries() if e["project_name"] == project), None)
