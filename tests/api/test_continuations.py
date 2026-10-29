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


def test_continuation_never_points_back_to_the_same_project(outputs_client):
    r = outputs_client.get(
        "/lineage/continuations",
        params={"project": "SP_CLO", "object_name": "CM_PAR_LOAN_TRADES", "column_name": "FDK_MT"},
    )
    assert all(h["project"] != "SP_CLO" for h in r.json())
