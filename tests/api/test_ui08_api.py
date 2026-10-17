import hashlib
import shutil
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT

sys.path.insert(0, str(ROOT / "api"))

from lineage_api.app import create_app  # noqa: E402
from lineage_api.db import DatabaseUnavailable, open_readonly  # noqa: E402
from lineage_api.migrations import add_business_process_columns  # noqa: E402


@pytest.fixture()
def db_file(lineage_db_path, tmp_path):
    target = tmp_path / "lineage.db"
    shutil.copy(lineage_db_path, target)
    c = sqlite3.connect(target)
    add_business_process_columns(c)
    c.close()
    return target


@pytest.fixture()
def client(db_file):
    return TestClient(create_app(str(db_file)))


@pytest.fixture()
def sp_clo(lineage_db_path):
    if lineage_db_path.parent.name != "SP_CLO":
        pytest.skip("SP_CLO-specific expectations")


def _target(client, object_name, column_name, source_project="SP_CLO"):
    objects = client.get("/targets", params={"project": "SP_CLO"}).json()
    obj = next(o for o in objects if o["object_name"] == object_name and o["source_project"] == source_project)
    cols = client.get(f"/targets/{obj['object_id']}/columns", params={"project": "SP_CLO"}).json()
    col = next(c for c in cols if c["column_name"] == column_name)
    return {"project": "SP_CLO", "object_id": obj["object_id"], "column_id": col["column_id"]}


def _error_code(response):
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    return body["error"]["code"]


# --- read endpoints on the real DB ----------------------------------------------------------------

def test_projects(client, sp_clo):
    r = client.get("/projects")
    assert r.status_code == 200
    assert r.json() == [{"project_name": "SP_CLO"}]


def test_targets_and_columns(client, sp_clo):
    r = client.get("/targets", params={"project": "SP_CLO"})
    assert r.status_code == 200
    got = [(o["object_name"], o["source_project"], o["column_count"]) for o in r.json()]
    assert got[0] == ("AR_PAR_LOAN_EVENTS", "SP_CLO", 46) and len(got) == 7
    obj = r.json()[0]
    cols = client.get(f"/targets/{obj['object_id']}/columns", params={"project": "SP_CLO"}).json()
    assert len(cols) == 46 and {"column_id", "column_name", "step_count"} == set(cols[0])
    assert next(c for c in cols if c["column_name"] == "MDE_CODE")["step_count"] == 3


def test_upstream_root_choices_and_children(client, sp_clo):
    t = _target(client, "PAR_UNPROCESSED_EVENTS", "CONTRACT_ID")
    r = client.get("/lineage/upstream", params=t)
    assert r.status_code == 200
    choices = r.json()["choices"]
    assert [c["source_column_name"] for c in choices] == ["AEF_EVENT_CODE", "AEF_OFFER_ID", "e_contract_id"]
    assert [c["has_more_upstream"] for c in choices] == [False, False, True]
    children = client.get("/lineage/upstream", params={"step_id": choices[2]["step_id"]}).json()["choices"]
    assert len(children) == 1 and children[0]["target_column_name"] == "e_contract_id"
    assert client.get("/lineage/upstream", params={"step_id": choices[0]["step_id"]}).json() == {"choices": []}


def test_ultimate_sources_full_and_filtered_by_step(client, sp_clo):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    full = client.get("/lineage/ultimate-sources", params=t).json()
    assert [s["column_name"] for s in full["terminal_sources"]] == [
        "OFR_HTCS_BOOK_CODE", "OFR_HTC_BOOK_CODE", "OFR_HTS_BOOK_CODE",
    ]
    roots = client.get("/lineage/upstream", params=t).json()["choices"]
    assert [c["upstream_choice_count"] for c in roots] == [1, 1]
    for chain in roots:
        filtered = client.get("/lineage/ultimate-sources", params={**t, "step_id": chain["step_id"]}).json()
        assert filtered["step_id"] == chain["step_id"]
        assert [s["column_name"] for s in filtered["terminal_sources"]] == [
            "OFR_HTCS_BOOK_CODE", "OFR_HTC_BOOK_CODE", "OFR_HTS_BOOK_CODE",
        ]


def test_remaining_depth(client, sp_clo):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    chain = next(c for c in client.get("/lineage/upstream", params=t).json()["choices"]
                 if c["upstream_choice_count"] == 1)
    r = client.get("/lineage/remaining-depth", params={"step_id": chain["step_id"]})
    assert r.status_code == 200
    assert r.json() == {
        "step_id": chain["step_id"], "is_terminal": False,
        "remaining_hops_exact": 3, "remaining_hops_min": 3, "remaining_hops_max": 3,
    }


def test_step_and_relation_detail(client, sp_clo):
    t = _target(client, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    (root,) = client.get("/lineage/upstream", params=t).json()["choices"]
    branch = next(c for c in client.get("/lineage/upstream", params={"step_id": root["step_id"]}).json()["choices"]
                  if c["driving_expression"] == "ELSE")
    step = client.get(f"/steps/{branch['step_id']}")
    assert step.status_code == 200
    body = step.json()
    assert body["result_expression"] == '"CLO"' and body["step_id"] == branch["step_id"]
    assert body["business_process"]["business_process_name"] == "AR_CLO_EVENT_PROCESSING"
    rel = client.get(f"/relations/{body['relation_id']}")
    assert rel.status_code == 200
    assert rel.json()["relation_id"] == body["relation_id"] and branch["step_id"] in rel.json()["step_ids"]


def test_not_persisted_reason_is_returned_as_stored(client, db_file):
    c = sqlite3.connect(db_file)
    step_id = c.execute("SELECT step_id FROM business_lineage_step WHERE relation_type='NOT_PERSISTED'").fetchone()[0]
    c.close()
    body = client.get(f"/steps/{step_id}").json()
    assert body["persistence"] == {
        "status": "NOT_PERSISTED",
        "reason_code": "TARGET_ATTRIBUTE_ABSENT_FROM_EDF_MAPPING",
        "reason": None,
    }


def test_every_step_is_served_as_json(client, db_file):
    c = sqlite3.connect(db_file)
    steps = [r[0] for r in c.execute("SELECT step_id FROM business_lineage_step")]
    c.close()
    for step_id in steps:
        assert client.get(f"/steps/{step_id}").status_code == 200
        assert client.get("/lineage/remaining-depth", params={"step_id": step_id}).status_code == 200
        assert client.get("/lineage/upstream", params={"step_id": step_id}).status_code == 200


# --- deterministic errors -------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path, params, status, code",
    [
        ("/targets", {"project": "NOPE"}, 404, "PROJECT_NOT_FOUND"),
        ("/targets/OBJ_x/columns", {"project": "SP_CLO"}, 404, "TARGET_OBJECT_NOT_FOUND"),
        ("/targets/OBJ_x/columns", {"project": "NOPE"}, 404, "PROJECT_NOT_FOUND"),
        ("/lineage/upstream", {"step_id": "BLS_nope"}, 404, "STEP_NOT_FOUND"),
        ("/lineage/remaining-depth", {"step_id": "BLS_nope"}, 404, "STEP_NOT_FOUND"),
        ("/steps/BLS_nope", {}, 404, "STEP_NOT_FOUND"),
        ("/relations/MAP_nope", {}, 404, "RELATION_NOT_FOUND"),
        ("/lineage/upstream", {}, 400, "INVALID_REQUEST"),
        ("/lineage/upstream", {"project": "SP_CLO", "object_id": "o"}, 400, "INVALID_REQUEST"),
        ("/targets", {}, 422, "VALIDATION_ERROR"),
        ("/lineage/remaining-depth", {}, 422, "VALIDATION_ERROR"),
        ("/lineage/ultimate-sources", {"project": "SP_CLO"}, 422, "VALIDATION_ERROR"),
        ("/no-such-route", {}, 404, "NOT_FOUND"),
    ],
)
def test_error_responses_are_deterministic(client, sp_clo, path, params, status, code):
    r = client.get(path, params=params)
    assert r.status_code == status
    assert _error_code(r) == code


def test_unknown_column_for_known_object(client, sp_clo):
    t = _target(client, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    for path in ("/lineage/upstream", "/lineage/ultimate-sources"):
        r = client.get(path, params={**t, "column_id": "COL_nope"})
        assert r.status_code == 404 and _error_code(r) == "TARGET_COLUMN_NOT_FOUND"


def test_ultimate_sources_rejects_step_from_other_target(client, sp_clo):
    a = _target(client, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    b = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    step = client.get("/lineage/upstream", params=b).json()["choices"][0]["step_id"]
    r = client.get("/lineage/ultimate-sources", params={**a, "step_id": step})
    assert r.status_code == 404 and _error_code(r) == "STEP_NOT_FOUND"


def test_error_responses_do_not_leak_sqlite_details(client, sp_clo):
    for r in (client.get("/steps/BLS_nope"), client.get("/targets", params={"project": "NOPE"})):
        text = r.text.lower()
        assert "sqlite" not in text and "traceback" not in text and ".db" not in text


# --- database availability and safety ------------------------------------------------------------

def test_missing_database_is_unavailable(tmp_path):
    r = TestClient(create_app(str(tmp_path / "missing.db"))).get("/projects")
    assert r.status_code == 503 and _error_code(r) == "DATABASE_UNAVAILABLE"
    assert "missing.db" not in r.text


def test_corrupt_database_is_unavailable(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database" * 100)
    r = TestClient(create_app(str(bad))).get("/projects")
    assert r.status_code == 503 and _error_code(r) == "DATABASE_UNAVAILABLE"


def test_unconfigured_database(monkeypatch):
    monkeypatch.delenv("LINEAGE_DB", raising=False)
    r = TestClient(create_app()).get("/projects")
    assert r.status_code == 503 and _error_code(r) == "DATABASE_NOT_CONFIGURED"


def test_database_path_can_come_from_environment(db_file, monkeypatch):
    monkeypatch.setenv("LINEAGE_DB", str(db_file))
    assert TestClient(create_app()).get("/projects").status_code == 200


def test_schema_without_business_process_columns_is_rejected(lineage_db_path, tmp_path):
    target = tmp_path / "old.db"
    shutil.copy(lineage_db_path, target)
    c = sqlite3.connect(target)
    for col in ("business_process_id", "business_process_name"):
        try:
            c.execute(f"ALTER TABLE business_lineage_step DROP COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    c.commit()
    c.close()
    r = TestClient(create_app(str(target))).get("/projects")
    assert r.status_code == 503 and _error_code(r) == "DATABASE_SCHEMA_MISMATCH"


def test_connection_is_read_only(db_file):
    conn = open_readonly(db_file)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("UPDATE business_lineage_step SET relation_type = 'X'")
    conn.close()
    with pytest.raises(DatabaseUnavailable):
        open_readonly(db_file.parent / "nope.db")


def test_requests_do_not_modify_the_database(client, db_file, sp_clo):
    before = hashlib.sha256(db_file.read_bytes()).hexdigest()
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    client.get("/projects")
    client.get("/lineage/upstream", params=t)
    client.get("/lineage/ultimate-sources", params=t)
    assert hashlib.sha256(db_file.read_bytes()).hexdigest() == before


def test_write_methods_are_not_exposed(client, sp_clo):
    for method in ("post", "put", "patch", "delete"):
        r = getattr(client, method)("/projects")
        assert r.status_code == 405 and _error_code(r) == "METHOD_NOT_ALLOWED"
