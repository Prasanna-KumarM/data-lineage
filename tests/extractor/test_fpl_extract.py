import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "api"))

from par_fpl_lineage import extract  # noqa: E402
from par_fpl_lineage.errors import BaselineNotFound  # noqa: E402
from par_fpl_lineage.parser.loader_info import find_loader_rows  # noqa: E402
from par_fpl_lineage.parser.views import find_views  # noqa: E402
from lineage_api.db import check_schema  # noqa: E402
from lineage_api.upstream import get_root_choices, get_upstream_choices  # noqa: E402
from lineage_api.target_catalog import list_target_columns, target_column_pairs, target_definitions  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "fpl_baseline"


@pytest.fixture()
def built(tmp_path):
    out = tmp_path / "FPL" / "lineage.db"
    report = extract(FIXTURE, out)
    conn = sqlite3.connect(out)
    conn.row_factory = sqlite3.Row
    yield conn, report
    conn.close()


def _walk(conn, target, column):
    cols = {c["column_name"]: c for c in list_target_columns(conn, "FPL", target["object_id"])}
    out = []
    for bp_id, root_obj, root_col in target_column_pairs(conn, "FPL", target["object_id"], cols[column]["column_id"]):
        out.extend(get_root_choices(conn, "FPL", root_obj, root_col, bp_id))
    return out


def test_parses_loader_rows():
    rows, issues = find_loader_rows(FIXTURE / "par_owner" / "ins" / "DB_codebase")
    assert issues == []
    assert [(r.par_source, r.par_table, r.portal_view) for r in rows] == [
        ("CLO", "AR_CLO_ACCOUNTING_EVENTS", "FPL_V_AR_CLO_AMS_ACCOUNTING_EVENTS"),
        ("LIQ", "AR_LIQ_ACCOUNTING_EVENTS", "FPL_V_AR_LIQ_AMS_ACCOUNTING_EVENTS"),
    ]


def test_parses_the_view():
    views, _ = find_views(FIXTURE / "par_owner" / "ins" / "DB_codebase")
    view = views["FPL_V_AR_CLO_AMS_ACCOUNTING_EVENTS"]
    assert len(view.sources) == 1
    source = view.sources[0]
    assert source.table == "CLO_AMS_ACCOUNTING_EVENTS_1"
    assert source.dblink == "fpl_par"
    kinds = {i.view_column: (i.kind, i.source_column or i.text) for i in source.items}
    assert kinds["PAR_SOURCE"] == ("constant", "'CLO'")
    assert kinds["PAR_STATUS"] == ("constant", "0")
    assert kinds["PAR_TIMESTAMP"] == ("function", "SYSDATE")
    assert kinds["AEF_EVENT_CODE"] == ("column", "AEF_EVENT_CODE")
    assert kinds["AEF_NOTE"][0] == "expression"
    assert view.issues


def test_builds_a_serving_database(built):
    conn, report = built
    check_schema(conn)
    assert report.loaders == 1

    targets = target_definitions(conn, "FPL")
    assert [t["object_name"] for t in targets] == ["AR_CLO_ACCOUNTING_EVENTS"]
    target = targets[0]
    assert target["column_count"] == 10
    cols = {c["column_name"]: c for c in list_target_columns(conn, "FPL", target["object_id"])}
    assert "AEF_NOT_IN_VIEW" not in cols
    assert set(cols) == {
        "PAR_ID", "PAR_PROCESSING_UNIT", "PAR_PROCESS_DATE",
        "PAR_SOURCE", "PAR_STATUS", "PAR_TIMESTAMP", "AEF_EVENT_CODE", "AEF_EVENT_DATE", "AEF_NOTE",
    }

    root = _walk(conn, target, "AEF_EVENT_CODE")
    assert [(r["source_object_name"], r["source_column_name"], r["relation_type"]) for r in root] == [
        ("FPL_V_AR_CLO_AMS_ACCOUNTING_EVENTS", "AEF_EVENT_CODE", "EXPLICIT_INATTR")
    ]
    below = get_upstream_choices(conn, root[0]["step_id"])
    assert [(r["source_object_name"], r["source_column_name"], r["has_more_upstream"]) for r in below] == [
        ("CLO_AMS_ACCOUNTING_EVENTS_1", "AEF_EVENT_CODE", False)
    ]

    const = get_upstream_choices(conn, _walk(conn, target, "PAR_SOURCE")[0]["step_id"])[0]
    assert (const["source_object_name"], const["source_column_name"], const["relation_type"]) == ("CONSTANT", "'CLO'", "CONSTANT_ASSIGNMENT")
    func = get_upstream_choices(conn, _walk(conn, target, "PAR_TIMESTAMP")[0]["step_id"])[0]
    assert (func["source_object_name"], func["source_column_name"], func["relation_type"]) == ("FUNCTION", "SYSDATE", "RUNTIME_FUNCTION_ASSIGNMENT")

    par_id = _walk(conn, target, "PAR_ID")
    assert par_id[0]["relation_type"] == "RUNTIME_FUNCTION_ASSIGNMENT"
    assert par_id[0]["source_column_name"] == "PAR_SEQ.NEXTVAL"
    assert par_id[0]["has_more_upstream"] is False

    note = _walk(conn, target, "AEF_NOTE")
    assert get_upstream_choices(conn, note[0]["step_id"]) == []
    reasons = {r["reason_code"] for r in conn.execute("SELECT reason_code FROM extraction_issue")}
    assert {"EXPRESSION_NOT_TRACED", "COLUMN_NOT_IN_VIEW", "VIEW_MISSING"} <= reasons


def test_source_filter_and_missing_view(tmp_path):
    report = extract(FIXTURE, tmp_path / "FPL" / "lineage.db", source="LIQ")
    assert report.loaders == 0
    assert [i.reason_code for i in report.issues] == ["VIEW_MISSING"]


def test_missing_baseline_is_a_clean_error(tmp_path):
    with pytest.raises(BaselineNotFound):
        extract(tmp_path / "nothing", tmp_path / "out" / "lineage.db")
    from par_fpl_lineage.cli.main import main

    assert main(["--baseline", str(tmp_path / "nothing"), "--output", str(tmp_path / "out" / "lineage.db")]) == 2


def test_duplicate_view_columns_are_reported_not_fatal(tmp_path):
    codebase = tmp_path / "b" / "par_owner" / "ins" / "DB_codebase"
    (codebase / "DML_baseline").mkdir(parents=True)
    (codebase / "Views").mkdir(parents=True)
    (codebase / "DML_baseline" / "l.sql").write_text(
        "Insert into PAR_PORTAL_LOADER_INFO (PAR_SOURCE,PAR_TABLE,PORTAL_DELIVERY_SET,PORTAL_VIEW,LOAD_IND)"
        " values ('CLO','AR_T','CLO_SET','FPL_V_DUP','Y');"
    )
    (codebase / "Views" / "v.sql").write_text(
        "CREATE OR REPLACE VIEW FPL_V_DUP AS SELECT A AS C1, B AS C1 FROM FPL_T@lnk /"
    )
    report = extract(tmp_path / "b", tmp_path / "out" / "lineage.db")
    assert report.relations == 5  # 3 loader columns + hop 1 and hop 2 for C1; the duplicate is skipped
    assert any(i.reason_code == "TABLE_DDL_MISSING" for i in report.issues)
    conn = sqlite3.connect(tmp_path / "out" / "lineage.db")
    assert conn.execute("SELECT COUNT(*) FROM extraction_issue WHERE message LIKE '%duplicate view column%'").fetchone()[0] == 1
    conn.close()
