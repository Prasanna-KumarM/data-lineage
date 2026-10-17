import sqlite3
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.catalog import (  # noqa: E402
    list_projects,
    list_target_columns,
    list_target_objects,
)
from lineage_api.migrations import add_business_process_columns  # noqa: E402


@pytest.fixture()
def synthetic():
    """Two projects that both contain a target object named ORDERS."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE business_process (business_process_id TEXT, business_process_name TEXT, project_name TEXT);
        CREATE TABLE canonical_object (object_id TEXT, object_name TEXT, source_project TEXT);
        CREATE TABLE business_lineage_step (
            step_id TEXT, root_target_object_id TEXT, root_target_object_name TEXT,
            root_target_column_id TEXT, root_target_column_name TEXT,
            business_process_id TEXT, business_process_name TEXT);
        INSERT INTO business_process VALUES ('BP1','Proc A','PRJ_A'), ('BP2','Proc B','PRJ_B');
        INSERT INTO canonical_object VALUES ('O1','ORDERS','PRJ_A'), ('O2','ORDERS','PRJ_B'),
                                            ('O3','ACCOUNTS','PRJ_A');
        INSERT INTO business_lineage_step VALUES
          ('S1','O1','ORDERS','C2','QTY','BP1','Proc A'),
          ('S2','O1','ORDERS','C1','ID','BP1','Proc A'),
          ('S3','O1','ORDERS','C1','ID','BP1','Proc A'),
          ('S4','O2','ORDERS','C9','ID','BP2','Proc B'),
          ('S5','O3','ACCOUNTS','C5','NUM','BP1','Proc A');
        """
    )
    yield c
    c.close()


def test_projects_sorted_and_distinct(synthetic):
    assert list_projects(synthetic) == ["PRJ_A", "PRJ_B"]


def test_same_object_name_is_disambiguated_by_project(synthetic):
    a = list_target_objects(synthetic, "PRJ_A")
    b = list_target_objects(synthetic, "PRJ_B")
    assert [o["object_id"] for o in a] == ["O3", "O1"]
    assert [o["object_id"] for o in b] == ["O2"]
    assert a[1]["object_name"] == b[0]["object_name"] == "ORDERS"


def test_object_entry_shape_and_column_count(synthetic):
    orders = list_target_objects(synthetic, "PRJ_A")[1]
    assert orders == {
        "object_id": "O1",
        "object_name": "ORDERS",
        "source_project": "PRJ_A",
        "business_processes": [{"business_process_id": "BP1", "business_process_name": "Proc A"}],
        "column_count": 2,
    }


def test_columns_ordered_and_scoped_to_object(synthetic):
    cols = list_target_columns(synthetic, "PRJ_A", "O1")
    assert [(c["column_name"], c["step_count"]) for c in cols] == [("ID", 2), ("QTY", 1)]
    assert list_target_columns(synthetic, "PRJ_B", "O1") == []


def test_unknown_project_returns_empty(synthetic):
    assert list_target_objects(synthetic, "NOPE") == []


@pytest.fixture()
def real(lineage_db_path, tmp_path):
    import shutil

    target = tmp_path / "lineage.db"
    shutil.copy(lineage_db_path, target)
    c = sqlite3.connect(target)
    c.row_factory = sqlite3.Row
    add_business_process_columns(c)
    yield c
    c.close()


def test_real_db_target_population_matches_roots(real):
    projects = list_projects(real)
    assert projects
    listed = {
        o["object_id"] for p in projects for o in list_target_objects(real, p)
    }
    roots = {r[0] for r in real.execute(
        "SELECT DISTINCT root_target_object_id FROM business_lineage_step")}
    assert listed == roots


def test_real_db_columns_have_lineage(real):
    for project in list_projects(real):
        for obj in list_target_objects(real, project):
            cols = list_target_columns(real, project, obj["object_id"])
            assert len(cols) == obj["column_count"] > 0
            assert all(c["step_count"] > 0 for c in cols)


@pytest.fixture()
def sp_clo(real, lineage_db_path):
    if lineage_db_path.parent.name != "SP_CLO":
        pytest.skip("SP_CLO-specific expectations")
    return real


def test_sp_clo_projects(sp_clo):
    assert list_projects(sp_clo) == ["SP_CLO"]


def test_sp_clo_target_objects_and_column_counts(sp_clo):
    got = [
        (o["object_name"], o["source_project"], o["column_count"])
        for o in list_target_objects(sp_clo, "SP_CLO")
    ]
    assert got == [
        ("AR_PAR_LOAN_EVENTS", "SP_CLO", 46),
        ("CM_PAR_LOAN_TRADES", "SP_CLO", 26),
        ("PAR_GFRS_CLO_TRADES", "SP_CLO", 37),
        ("PAR_UNPROCESSED_EVENTS", "GP_SHARED", 1),
        ("PAR_UNPROCESSED_EVENTS", "SP_CLO", 35),
        ("PAR_UNPROCESSED_TRADES", "GP_SHARED", 1),
        ("PAR_UNPROCESSED_TRADES", "SP_CLO", 14),
    ]


def test_sp_clo_same_named_objects_have_distinct_ids(sp_clo):
    objs = list_target_objects(sp_clo, "SP_CLO")
    for name in ("PAR_UNPROCESSED_EVENTS", "PAR_UNPROCESSED_TRADES"):
        ids = [o["object_id"] for o in objs if o["object_name"] == name]
        assert len(ids) == 2 and len(set(ids)) == 2


def test_sp_clo_business_process_per_object(sp_clo):
    bps = {
        o["object_name"]: {b["business_process_name"] for b in o["business_processes"]}
        for o in list_target_objects(sp_clo, "SP_CLO")
    }
    assert bps["AR_PAR_LOAN_EVENTS"] == {"AR_CLO_EVENT_PROCESSING"}
    assert bps["PAR_UNPROCESSED_TRADES"] == {"CM_CLO_OFFER"}


def test_sp_clo_regression_target_column_is_listed(sp_clo):
    obj = next(o for o in list_target_objects(sp_clo, "SP_CLO")
               if o["object_name"] == "AR_PAR_LOAN_EVENTS")
    cols = {c["column_name"]: c["step_count"] for c in list_target_columns(sp_clo, "SP_CLO", obj["object_id"])}
    assert cols["MDE_CODE"] == 3
    assert sum(cols.values()) == 71
    assert list(cols) == sorted(cols)


def test_sp_clo_wrong_project_for_object_returns_no_columns(sp_clo):
    obj = list_target_objects(sp_clo, "SP_CLO")[0]
    assert list_target_columns(sp_clo, "OTHER", obj["object_id"]) == []
