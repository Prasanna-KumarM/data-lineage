import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "api"))

from par_fpl_lineage.baseline import find_loader_rows, find_views  # noqa: E402
from par_fpl_lineage.build import build  # noqa: E402
from lineage_api.db import check_schema  # noqa: E402
from lineage_api.upstream import get_root_choices, get_upstream_choices  # noqa: E402
from lineage_api.target_catalog import list_target_columns, target_definitions  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "fpl_baseline"


@pytest.fixture()
def built(tmp_path):
    out = tmp_path / "FPL" / "lineage.db"
    stats = build(FIXTURE, out)
    conn = sqlite3.connect(out)
    conn.row_factory = sqlite3.Row
    yield conn, stats
    conn.close()


def test_parses_loader_rows():
    rows = find_loader_rows(FIXTURE / "par_owner" / "ins" / "DB_codebase")
    assert [(r.par_source, r.par_table, r.portal_view) for r in rows] == [
        ("CLO", "AR_CLO_ACCOUNTING_EVENTS", "FPL_V_AR_CLO_AMS_ACCOUNTING_EVENTS"),
        ("LIQ", "AR_LIQ_ACCOUNTING_EVENTS", "FPL_V_AR_LIQ_AMS_ACCOUNTING_EVENTS"),
    ]


def test_parses_the_view():
    views = find_views(FIXTURE / "par_owner" / "ins" / "DB_codebase")
    view = views["FPL_V_AR_CLO_AMS_ACCOUNTING_EVENTS"]
    assert view.from_table == "CLO_AMS_ACCOUNTING_EVENTS_1"
    assert view.dblink == "fpl_par"
    kinds = {i.view_column: (i.kind, i.source_column or i.text) for i in view.items}
    assert kinds["PAR_SOURCE"] == ("constant", "'CLO'")
    assert kinds["PAR_STATUS"] == ("constant", "0")
    assert kinds["PAR_TIMESTAMP"] == ("function", "SYSDATE")
    assert kinds["AEF_EVENT_CODE"] == ("column", "AEF_EVENT_CODE")
    assert kinds["AEF_NOTE"][0] == "expression"
    assert view.issues


def test_builds_a_serving_database(built):
    conn, stats = built
    check_schema(conn)
    assert stats["loaders"] == 1

    targets = target_definitions(conn, "FPL")
    assert [t["object_name"] for t in targets] == ["AR_CLO_ACCOUNTING_EVENTS"]
    target = targets[0]
    assert target["column_count"] == 10
    cols = {c["column_name"]: c for c in list_target_columns(conn, "FPL", target["object_id"])}
    # The loader-only column and the not-in-view column have no mapping.
    assert "AEF_NOT_IN_VIEW" not in cols
    assert set(cols) == {
        "PAR_ID", "PAR_PROCESSING_UNIT", "PAR_PROCESS_DATE",
        "PAR_SOURCE", "PAR_STATUS", "PAR_TIMESTAMP", "AEF_EVENT_CODE", "AEF_EVENT_DATE", "AEF_NOTE",
    }

    def walk(column):
        pairs = [(r["root_target_object_id"], r["root_target_column_id"]) for r in []]
        pairs = target_pairs(conn, target["object_id"], cols[column]["column_id"])
        root = get_root_choices(conn, "FPL", *pairs[0][1:], pairs[0][0])
        return root

    # Hop 1: view column; hop 2: FPL table column, terminal.
    root = walk("AEF_EVENT_CODE")
    assert [(r["source_object_name"], r["source_column_name"], r["relation_type"]) for r in root] == [
        ("FPL_V_AR_CLO_AMS_ACCOUNTING_EVENTS", "AEF_EVENT_CODE", "EXPLICIT_INATTR")
    ]
    below = get_upstream_choices(conn, root[0]["step_id"])
    assert [(r["source_object_name"], r["source_column_name"], r["has_more_upstream"]) for r in below] == [
        ("CLO_AMS_ACCOUNTING_EVENTS_1", "AEF_EVENT_CODE", False)
    ]

    # View constants and functions.
    assert walk("PAR_SOURCE")[0]["relation_type"] == "EXPLICIT_INATTR"
    const = get_upstream_choices(conn, walk("PAR_SOURCE")[0]["step_id"])[0]
    assert (const["source_object_name"], const["source_column_name"], const["relation_type"]) == ("CONSTANT", "'CLO'", "CONSTANT_ASSIGNMENT")
    func = get_upstream_choices(conn, walk("PAR_TIMESTAMP")[0]["step_id"])[0]
    assert (func["source_object_name"], func["source_column_name"], func["relation_type"]) == ("FUNCTION", "SYSDATE", "RUNTIME_FUNCTION_ASSIGNMENT")

    # Loader-filled columns are terminal at hop 1.
    par_id = walk("PAR_ID")
    assert par_id[0]["relation_type"] == "RUNTIME_FUNCTION_ASSIGNMENT"
    assert par_id[0]["source_column_name"] == "PAR_SEQ.NEXTVAL"
    assert par_id[0]["has_more_upstream"] is False

    # Expression-backed view column: hop 1 exists, hop 2 is an extraction issue instead.
    note = walk("AEF_NOTE")
    assert get_upstream_choices(conn, note[0]["step_id"]) == []
    issues = conn.execute("SELECT reason_code, message FROM extraction_issue").fetchall()
    assert any(r["reason_code"] == "EXPRESSION_NOT_TRACED" and "AEF_NOTE" in r["message"] for r in issues)
    assert any(r["reason_code"] == "COLUMN_NOT_IN_VIEW" for r in issues)


def target_pairs(conn, object_id, column_id):
    from lineage_api.target_catalog import target_column_pairs

    return target_column_pairs(conn, "FPL", object_id, column_id)


def test_source_filter_and_missing_view(tmp_path):
    out = tmp_path / "FPL" / "lineage.db"
    stats = build(FIXTURE, out, source_filter="LIQ")
    conn = sqlite3.connect(out)
    assert stats["loaders"] == 0 and stats["views_missing"] == 1
    assert conn.execute("SELECT COUNT(*) FROM extraction_issue WHERE reason_code='VIEW_MISSING'").fetchone()[0] == 1
    conn.close()
