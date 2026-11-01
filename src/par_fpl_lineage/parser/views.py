"""Parse view DDL from Views/: view column list, select items, FROM table(s) with @dblink, UNION branches."""
from __future__ import annotations

import re
from pathlib import Path

from par_fpl_lineage.models import Issue, ViewDef, ViewItem, ViewSource
from par_fpl_lineage.parser.sqltext import split_top_level

_VIEW_RE = re.compile(
    r"create\s+or\s+replace\s+(?:force\s+)?view\s+[\w.]*?(\w+)\s*(?:\((.*?)\))?"
    r"(?:\s+bequeath\s+\w+)?\s+as\s+(.*?)\s+from\s+([\w.]+)(@[\w.]+)?(.*?);?\s*/?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONST_RE = re.compile(r"^('[^']*'|-?\d+(?:\.\d+)?)(?:\s+as\s+(\w+))?$", re.IGNORECASE)
_FUNC_RE = re.compile(r"^(\w[\w.]*\s*\(\s*\)|sysdate|current_timestamp)(?:\s+as\s+(\w+))?$", re.IGNORECASE)
_PLAIN_COL_RE = re.compile(r"^(\w+)$")
_ALIAS_RE = re.compile(r"^(.*?)\s+as\s+(\w+)$", re.IGNORECASE | re.DOTALL)
_UNION_RE = re.compile(
    r"union\s+(?:all\s+)?(?:select\s+)?(.*?)\s+from\s+([\w.]+)(@[\w.]+)?",
    re.IGNORECASE | re.DOTALL,
)


def _classify(raw: str, view_col: str | None) -> tuple[ViewItem, str | None]:
    """One select item → ViewItem, plus a note when it is not traceable."""
    item = raw.strip()
    m = _CONST_RE.match(item)
    if m:
        return ViewItem("constant", view_col or m.group(2) or m.group(1), text=m.group(1)), None
    m = _FUNC_RE.match(item)
    if m:
        return ViewItem("function", view_col or m.group(2) or m.group(1), text=m.group(1)), None
    m = _PLAIN_COL_RE.match(item)
    if m:
        return ViewItem("column", view_col or m.group(1), source_column=m.group(1)), None
    m = _ALIAS_RE.match(item)
    if m and _PLAIN_COL_RE.match(m.group(1).strip()):
        return ViewItem("column", view_col or m.group(2), source_column=m.group(1).strip()), None
    return ViewItem("expression", view_col or (m.group(2) if m else item), text=item), (
        f"select item not a plain column/constant/function: {item[:80]}"
    )


def _classify_list(select_list: str, view_cols: list[str]) -> tuple[list[ViewItem], list[str]]:
    items, issues = [], []
    for index, raw in enumerate(split_top_level(select_list)):
        view_col = view_cols[index] if index < len(view_cols) else None
        item, note = _classify(raw, view_col)
        items.append(item)
        if note:
            issues.append(note)
    return items, issues


def parse_view(text: str, locator: str) -> ViewDef | None:
    match = _VIEW_RE.search(text)
    if not match:
        return None
    name, col_list, select_list, from_table, dblink, tail = match.groups()
    select_list = re.sub(r"^\s*select\s+(?:distinct\s+)?", "", select_list, flags=re.IGNORECASE)
    view_cols = [c.strip() for c in col_list.split(",")] if col_list else []
    issues: list[str] = []
    if re.search(r"\bwhere\b|\bjoin\b|\bgroup\s+by\b", tail or "", re.IGNORECASE):
        issues.append("view has WHERE/JOIN/GROUP BY; column mapping may be incomplete")

    items, item_issues = _classify_list(select_list, view_cols)
    issues.extend(item_issues)
    sources = [ViewSource(from_table.split(".")[-1].upper(), (dblink or "").lstrip("@") or None, items)]

    # Additional UNION [ALL] branches map positionally to the same view columns.
    for branch in _UNION_RE.finditer(tail or ""):
        branch_items, branch_issues = _classify_list(branch.group(1), view_cols)
        issues.extend(branch_issues)
        sources.append(ViewSource(branch.group(2).split(".")[-1].upper(), (branch.group(3) or "").lstrip("@") or None, branch_items))
    if len(sources) > 1:
        issues.append(f"view UNIONs {len(sources)} tables; each branch is mapped separately")

    # Duplicate view column names would collide in the relation ids; keep the first.
    seen: set[str] = set()
    for source in sources:
        deduped: list[ViewItem] = []
        for item in source.items:
            if item.view_column in seen:
                issues.append(f"duplicate view column {item.view_column}; later occurrence ignored")
                continue
            seen.add(item.view_column)
            deduped.append(item)
        source.items[:] = deduped

    return ViewDef(name=name.upper(), locator=locator, sources=sources, issues=issues)


def find_views(codebase: Path) -> tuple[dict[str, ViewDef], list[Issue]]:
    views: dict[str, ViewDef] = {}
    issues: list[Issue] = []
    root = codebase / "Views"
    if not root.is_dir():
        issues.append(Issue("VIEWS_DIR_MISSING", f"no Views/ directory under {codebase}", str(root)))
        return views, issues
    for file in sorted(root.rglob("*.sql")):
        try:
            text = file.read_text(errors="replace")
        except OSError as exc:
            issues.append(Issue("FILE_UNREADABLE", str(exc), str(file)))
            continue
        view = parse_view(text, str(file.relative_to(codebase)))
        if view:
            views[view.name] = view
    return views, issues
