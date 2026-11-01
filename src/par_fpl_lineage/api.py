"""Public entry point: extract(baseline, output, source=None) -> ExtractionReport."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from par_fpl_lineage.canonical.writer import CanonicalWriter
from par_fpl_lineage.config import settings
from par_fpl_lineage.db.database import create_database
from par_fpl_lineage.errors import BaselineNotFound
from par_fpl_lineage.lineage.assemble import assemble_loader_row
from par_fpl_lineage.models import Issue
from par_fpl_lineage.parser.loader_info import find_loader_rows
from par_fpl_lineage.parser.tables import find_table_columns
from par_fpl_lineage.parser.views import find_views
from par_fpl_lineage.reporting.report import ExtractionReport, persist_issues


def extract(baseline: str | Path, output: str | Path, source: str | None = None) -> ExtractionReport:
    """Read the baseline checkout and write the FPL lineage database.

    Raises BaselineNotFound when par_owner/ins/DB_codebase is missing.
    Unreadable files and unparseable content become issues, never fatal.
    """
    baseline = Path(baseline)
    codebase = baseline / settings.CODEBASE_RELATIVE
    if not codebase.is_dir():
        raise BaselineNotFound(f"DB_codebase not found under {baseline} (expected {settings.CODEBASE_RELATIVE})")

    loader_rows, issues = find_loader_rows(codebase)
    views, view_issues = find_views(codebase)
    tables, table_issues = find_table_columns(codebase)
    issues = issues + view_issues + table_issues

    loader_rows = [r for r in loader_rows if r.par_table and r.portal_view]
    if source:
        loader_rows = [r for r in loader_rows if r.par_source == source]

    run_id = f"{settings.PROJECT}-{datetime.now(timezone.utc).isoformat()}"
    report = ExtractionReport(issues=list(issues))
    conn = create_database(Path(output))
    try:
        conn.execute(
            "INSERT INTO extraction_run VALUES (?,?,?,?,?,?,?,?)",
            (run_id, str(baseline), None, settings.PARSER_VERSION, settings.SCHEMA_VERSION, settings.IDENTITY_VERSION,
             datetime.now(timezone.utc).isoformat(), "SUCCESS"),
        )
        writer = CanonicalWriter(conn, lambda reason, message, bp: report.issues.append(Issue(reason, message, "", "WARNING", bp)))
        used_bp_names: set[str] = set()
        for row in loader_rows:
            try:
                written = assemble_loader_row(writer, row, views.get(row.portal_view.upper()), tables, used_bp_names)
            except sqlite3.Error as exc:
                report.issues.append(Issue("WRITE_FAILED", f"{row.par_table}: {exc}", row.locator, "ERROR"))
                continue
            report.loaders += 1 if written or views.get(row.portal_view.upper()) else 0
            report.relations += written
        report.steps = conn.execute("SELECT COUNT(*) FROM business_lineage_step").fetchone()[0]
        persist_issues(conn, run_id, report.issues)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        Path(output).unlink(missing_ok=True)
        raise
    conn.close()
    return report
