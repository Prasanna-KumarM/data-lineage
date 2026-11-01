"""Extraction report and issue persistence."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from par_fpl_lineage.models import Issue


@dataclass
class ExtractionReport:
    loaders: int = 0
    relations: int = 0
    steps: int = 0
    issues: list[Issue] = field(default_factory=list)

    def by_reason(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.reason_code] = counts.get(issue.reason_code, 0) + 1
        return counts

    def summary_line(self) -> str:
        parts = [f"loader entries: {self.loaders}", f"relations: {self.relations}", f"steps: {self.steps}"]
        for reason, count in sorted(self.by_reason().items()):
            parts.append(f"{reason}: {count}")
        return ", ".join(parts)


def persist_issues(conn: sqlite3.Connection, run_id: str, issues: list[Issue]) -> None:
    for index, issue in enumerate(issues, start=1):
        conn.execute(
            "INSERT INTO extraction_issue VALUES (?,?,?,?,?,?,?,?)",
            (f"EXI_{run_id}_{index}", run_id, issue.severity, issue.reason_code, issue.message, issue.locator, None, None),
        )
