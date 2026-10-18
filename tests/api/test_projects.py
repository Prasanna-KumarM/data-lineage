import shutil
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT

sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.app import create_app  # noqa: E402
from lineage_api.catalog import list_target_objects  # noqa: E402
from lineage_api.migrations import add_business_process_columns  # noqa: E402
from lineage_api.projects import ProjectRegistry  # noqa: E402


@pytest.fixture()
def sp_clo_db(lineage_db_path, tmp_path):
    if lineage_db_path.parent.name != "SP_CLO":
        pytest.skip("SP_CLO-specific expectations")
    target = tmp_path / "sp_clo.db"
    shutil.copy(lineage_db_path, target)
    c = sqlite3.connect(target)
    add_business_process_columns(c)
    c.close()
    return target


def _folder(outputs, name, source=None, rename_to=None):
    folder = outputs / name
    folder.mkdir(parents=True)
    db = folder / "lineage.db"
    if source is None:
        sqlite3.connect(db).close()  # an empty file: exists but is not a lineage database
    else:
        shutil.copy(source, db)
        if rename_to:
            c = sqlite3.connect(db)
            c.execute("UPDATE business_process SET project_name = ?", (rename_to,))
            c.commit()
            c.close()
    return db


@pytest.fixture()
def outputs(tmp_path, sp_clo_db):
    out = tmp_path / "outputs"
    _folder(out, "SP_CLO", sp_clo_db)
    _folder(out, "SP_TWO", sp_clo_db, rename_to="SP_TWO")
    return out


def test_lists_one_project_per_folder_that_holds_a_lineage_db(outputs):
    (outputs / "empty_folder").mkdir()
    (outputs / "notes.txt").write_text("x")
    (outputs / "other").mkdir()
    (outputs / "other" / "something_else.db").write_text("x")
    client = TestClient(create_app(outputs_dir=str(outputs)))
    r = client.get("/projects")
    assert r.status_code == 200
    assert r.json() == [
        {"project_name": "SP_CLO", "folder": "SP_CLO"},
        {"project_name": "SP_TWO", "folder": "SP_TWO"},
    ]


def test_a_folder_added_later_appears_without_a_restart(outputs, sp_clo_db):
    client = TestClient(create_app(outputs_dir=str(outputs)))
    assert [p["project_name"] for p in client.get("/projects").json()] == ["SP_CLO", "SP_TWO"]
    _folder(outputs, "SP_THREE", sp_clo_db, rename_to="SP_THREE")
    assert [p["project_name"] for p in client.get("/projects").json()] == ["SP_CLO", "SP_THREE", "SP_TWO"]
    shutil.rmtree(outputs / "SP_THREE")
    assert [p["project_name"] for p in client.get("/projects").json()] == ["SP_CLO", "SP_TWO"]


def test_a_database_that_cannot_be_used_is_listed_with_the_reason(outputs):
    _folder(outputs, "GP_BROKEN")
    client = TestClient(create_app(outputs_dir=str(outputs)))
    broken = next(p for p in client.get("/projects").json() if p["project_name"] == "GP_BROKEN")
    assert broken["ready"] is False
    assert "migrated" in broken["problem"]
    assert client.get("/targets", params={"project": "GP_BROKEN"}).status_code == 503
    # The other projects keep working.
    assert client.get("/targets", params={"project": "SP_CLO"}).status_code == 200


def test_each_project_is_served_from_its_own_database(outputs):
    client = TestClient(create_app(outputs_dir=str(outputs)))
    one = client.get("/targets", params={"project": "SP_CLO"}).json()
    two = client.get("/targets", params={"project": "SP_TWO"}).json()
    assert one and [o["object_id"] for o in one] == [o["object_id"] for o in two]
    # A project name from the other database is not found in this one.
    c = sqlite3.connect(outputs / "SP_TWO" / "lineage.db")
    c.execute("UPDATE business_process SET project_name = 'ONLY_IN_TWO'")
    c.commit()
    c.close()
    assert client.get("/targets", params={"project": "SP_TWO"}).status_code == 404
    assert client.get("/targets", params={"project": "ONLY_IN_TWO"}).status_code == 200
    assert client.get("/targets", params={"project": "SP_CLO"}).status_code == 200


def test_requests_without_a_project_parameter_use_the_project_header(outputs):
    client = TestClient(create_app(outputs_dir=str(outputs)))
    step = None
    c = sqlite3.connect(outputs / "SP_TWO" / "lineage.db")
    step = c.execute("SELECT step_id FROM business_lineage_step LIMIT 1").fetchone()[0]
    c.close()
    assert client.get(f"/steps/{step}").status_code == 400
    assert client.get(f"/steps/{step}", headers={"X-Lineage-Project": "NOPE"}).status_code == 404
    r = client.get(f"/steps/{step}", headers={"X-Lineage-Project": "SP_TWO"})
    assert r.status_code == 200 and r.json()["step_id"] == step
    assert client.get("/lineage/remaining-depth", params={"step_id": step}, headers={"X-Lineage-Project": "SP_CLO"}).status_code == 200


def test_summary_and_graph_work_for_a_project_in_the_folder(outputs):
    client = TestClient(create_app(outputs_dir=str(outputs)))
    c = sqlite3.connect(outputs / "SP_TWO" / "lineage.db")
    c.row_factory = sqlite3.Row
    obj = next(o for o in list_target_objects(c, "SP_TWO") if o["object_name"] == "CM_PAR_LOAN_TRADES")
    c.close()
    summary = client.get(f"/targets/{obj['object_id']}/summary", params={"project": "SP_TWO"})
    assert summary.status_code == 200
    column = next(x for x in summary.json()["columns"] if x["column_name"] == "FDK_MT")
    graph = client.get("/lineage/graph", params={"project": "SP_TWO", "object_id": obj["object_id"], "column_id": column["column_id"]})
    assert graph.status_code == 200 and graph.json()["totals"]["sources"] == 3


def test_a_project_name_cannot_escape_the_outputs_folder(outputs):
    client = TestClient(create_app(outputs_dir=str(outputs)))
    for name in ("../outputs/SP_CLO", "..", "/etc", "SP_CLO/../SP_TWO"):
        r = client.get("/targets", params={"project": name})
        assert r.status_code == 404, name


def test_a_fixed_database_still_behaves_as_before(sp_clo_db):
    client = TestClient(create_app(str(sp_clo_db)))
    assert client.get("/projects").json() == [{"project_name": "SP_CLO"}]


def test_a_duplicate_project_name_keeps_the_first_folder(outputs, sp_clo_db):
    _folder(outputs, "ZZ_COPY", sp_clo_db)  # also holds SP_CLO
    entries = ProjectRegistry(outputs).entries()
    assert [e["project_name"] for e in entries].count("SP_CLO") == 1
    assert next(e for e in entries if e["project_name"] == "SP_CLO")["folder"] == "SP_CLO"
