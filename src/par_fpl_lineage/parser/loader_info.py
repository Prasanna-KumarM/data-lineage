"""Parse PAR_PORTAL_LOADER_INFO seed inserts from DML_baseline/DML_delta."""
from __future__ import annotations

import re
from pathlib import Path

from par_fpl_lineage.models import Issue, LoaderRow
from par_fpl_lineage.parser.sqltext import split_insert_values

LOADER_TABLE = "PAR_PORTAL_LOADER_INFO"
_INSERT_RE = re.compile(
    r"insert\s+into\s+\w*\.*" + LOADER_TABLE + r"\s*\(([^)]*)\)\s*values\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)


def find_loader_rows(codebase: Path) -> tuple[list[LoaderRow], list[Issue]]:
    """All loader rows, and an issue per file that cannot be read."""
    rows: list[LoaderRow] = []
    issues: list[Issue] = []
    for folder in ("DML_baseline", "DML_delta"):
        root = codebase / folder
        if not root.is_dir():
            continue
        for file in sorted(root.rglob("*.sql")):
            try:
                text = file.read_text(errors="replace")
            except OSError as exc:
                issues.append(Issue("FILE_UNREADABLE", str(exc), str(file)))
                continue
            for match in _INSERT_RE.finditer(text):
                cols = [c.strip().upper() for c in match.group(1).split(",")]
                row = dict(zip(cols, split_insert_values(match.group(2))))
                rows.append(
                    LoaderRow(
                        par_source=row.get("PAR_SOURCE") or "",
                        par_table=row.get("PAR_TABLE") or "",
                        portal_view=row.get("PORTAL_VIEW") or "",
                        delivery_set=row.get("PORTAL_DELIVERY_SET"),
                        locator=str(file.relative_to(codebase)),
                    )
                )
    return rows, issues
