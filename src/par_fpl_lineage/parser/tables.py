"""Parse table DDL from Tables_baseline/Tables_delta for column lists."""
from __future__ import annotations

import re
from pathlib import Path

from par_fpl_lineage.models import Issue
from par_fpl_lineage.parser.sqltext import split_top_level

_TABLE_RE = re.compile(r"create\s+table\s+[\w.]*?(\w+)\s*\((.*?)\)\s*(?:\w[\w\s]*)?;", re.IGNORECASE | re.DOTALL)
_CONSTRAINT_START = ("constraint", "primary", "foreign", "unique", "check")


def parse_table_columns(text: str) -> list[str]:
    match = _TABLE_RE.search(text)
    if not match:
        return []
    columns = []
    for part in split_top_level(match.group(2)):
        first = part.strip().split(None, 1)[0].strip('"').upper() if part.strip() else ""
        if first and not first.lower().startswith(_CONSTRAINT_START):
            columns.append(first)
    return columns


def find_table_columns(codebase: Path) -> tuple[dict[str, list[str]], list[Issue]]:
    tables: dict[str, list[str]] = {}
    issues: list[Issue] = []
    for folder in ("Tables_baseline", "Tables_delta"):
        root = codebase / folder
        if not root.is_dir():
            continue
        for file in sorted(root.rglob("*.sql")):
            try:
                text = file.read_text(errors="replace")
            except OSError as exc:
                issues.append(Issue("FILE_UNREADABLE", str(exc), str(file)))
                continue
            for match in re.finditer(r"create\s+table\s+[\w.]*?(\w+)\s*\(", text, re.IGNORECASE):
                name = match.group(1).upper()
                cols = parse_table_columns(text[match.start():])
                if cols and name not in tables:
                    tables[name] = cols
                elif not cols:
                    issues.append(Issue("TABLE_PARSE", f"no columns parsed for table {name}", str(file.relative_to(codebase))))
    return tables, issues
