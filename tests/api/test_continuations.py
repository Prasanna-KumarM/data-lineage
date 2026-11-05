import pytest
from fastapi.testclient import TestClient

from conftest import ROOT

import sys
sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.app import create_app  # noqa: E402


@pytest.fixture()
def outputs_client():
    outputs = ROOT / "outputs"
    if not (outputs / "SP_CLO" / "lineage.db").is_file() or not (outputs / "SP_LIQ" / "lineage.db").is_file():
        pytest.skip("both project DBs are required")
    return TestClient(create_app(outputs_dir=str(outputs)))


def test_ultimate_source_of_liq_continues_as_target_in_clo(outputs_client):
    r = outputs_client.get(
        "/lineage/continuations",
        params={"project": "SP_LIQ", "object_name": "CM_PAR_LOAN_TRADES", "column_name": "FDK_MT"},
    )
    assert r.status_code == 200
    hits = r.json()
    assert [h["project"] for h in hits] == ["SP_CLO"]
    clo_targets = outputs_client.get("/targets", params={"project": "SP_CLO"}).json()
    target = next(t for t in clo_targets if t["object_name"] == "CM_PAR_LOAN_TRADES")
    assert hits[0]["object_id"] == target["object_id"]
    columns = outputs_client.get(f"/targets/{target['object_id']}/columns", params={"project": "SP_CLO"}).json()
    assert hits[0]["column_id"] == next(c["column_id"] for c in columns if c["column_name"] == "FDK_MT")


def test_no_continuation_returns_empty(outputs_client):
    r = outputs_client.get(
        "/lineage/continuations",
        params={"project": "SP_LIQ", "object_name": "CM_LIQ_PORTF_ACCRUAL", "column_name": "NO_SUCH_COLUMN"},
    )
    assert r.status_code == 200
    assert r.json() == []


def test_target_definitions_are_cached_across_continuation_calls():
    outputs = ROOT / "outputs"
    if not (outputs / "SP_CLO" / "lineage.db").is_file() or not (outputs / "SP_LIQ" / "lineage.db").is_file():
        pytest.skip("both project DBs are required")
    app = create_app(outputs_dir=str(outputs))
    client = TestClient(app)
    params = {"project": "SP_LIQ", "object_name": "CM_PAR_LOAN_TRADES", "column_name": "FDK_MT"}
    first = client.get("/lineage/continuations", params=params)
    assert first.status_code == 200
    computed = app.state.catalog_cache.compute_count
    assert computed > 0
    for _ in range(5):
        r = client.get("/lineage/continuations", params=params)
        assert r.status_code == 200
        assert r.json() == first.json()
    assert app.state.catalog_cache.compute_count == computed


def test_catalog_cache_computes_once_under_concurrency():
    import threading

    from lineage_api.db import open_readonly
    from lineage_api.target_catalog import TargetCatalogCache

    db = ROOT / "outputs" / "SP_CLO" / "lineage.db"
    if not db.is_file():
        pytest.skip("project DB required")
    cache = TargetCatalogCache()
    results, errors = [], []

    def worker():
        try:
            conn = open_readonly(db)
            try:
                results.append(cache.get(conn, "SP_CLO"))
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert cache.compute_count == 1
    assert all(r is results[0] for r in results)


def test_continuation_never_points_back_to_the_same_project(outputs_client):
    r = outputs_client.get(
        "/lineage/continuations",
        params={"project": "SP_CLO", "object_name": "CM_PAR_LOAN_TRADES", "column_name": "FDK_MT"},
    )
    assert all(h["project"] != "SP_CLO" for h in r.json())


def test_continuation_only_projects_are_not_startable(tmp_path):
    import shutil

    src = ROOT / "outputs" / "SP_CLO" / "lineage.db"
    for folder, marker, app in (("PAR_APP", False, "PAR"), ("FPL", True, "FPL")):
        d = tmp_path / folder
        d.mkdir()
        shutil.copy(src, d / "lineage.db")
        (d / "application").write_text(app)
        if marker:
            (d / "continuation_only").touch()
    client = TestClient(create_app(outputs_dir=str(tmp_path)))
    # Both copies report the same internal project name, so the second folder is unusable; assert by folder.
    projects = {p["folder"]: p for p in client.get("/projects").json()}
    assert "startable" not in projects["PAR_APP"]
    assert projects["FPL"]["startable"] is False
    assert projects["PAR_APP"]["application"] == "PAR"
    assert projects["FPL"]["application"] == "FPL"
    # It still answers lineage calls.
    assert client.get("/targets", params={"project": "SP_CLO"}).status_code == 200
