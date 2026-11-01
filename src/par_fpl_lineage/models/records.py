"""Records parsed from the baseline scripts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ItemKind = Literal["column", "constant", "function", "expression"]


@dataclass(frozen=True)
class LoaderRow:
    """One PAR_PORTAL_LOADER_INFO row: a PAR table loaded from a portal view."""

    par_source: str
    par_table: str
    portal_view: str
    delivery_set: str | None
    locator: str


@dataclass(frozen=True)
class ViewItem:
    """One entry of a view's select list, mapped to a view column."""

    kind: ItemKind
    view_column: str
    source_column: str | None = None  # kind == "column"
    text: str | None = None  # raw text for constant/function/expression


@dataclass(frozen=True)
class ViewSource:
    """One FROM branch of a view (a UNION branch or the only table)."""

    table: str
    dblink: str | None
    items: list[ViewItem]


@dataclass
class ViewDef:
    name: str
    locator: str
    sources: list[ViewSource]
    issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Issue:
    """A non-fatal extraction problem; written to extraction_issue and reported."""

    reason_code: str
    message: str
    locator: str
    severity: str = "WARNING"
    business_process: str | None = None
