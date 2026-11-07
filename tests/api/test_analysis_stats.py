import shutil
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT

sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.app import create_app  # noqa: E402


@pytest.fixture()
def outputs(tmp_path):
    clo = ROOT / "outputs" / "SP_CLO" / "lineage.db"
    if not clo.is_file():
        pytest.skip("SP_CLO lineage DB required")
    folder = tmp_path / "SP_CLO"
    folder.mkdir()
    shutil.copy(clo, folder / "lineage.db")
    return tmp_path


def test_stats_match_the_table_summary(outputs):
    client = TestClient(create_app(outputs_dir=str(outputs)))
    object_id = next(
        o["object_id"] for o in client.get("/targets", params={"project": "SP_CLO"}).json() if o["object_name"] == "CM_PAR_LOAN_TRADES"
    )
    totals = client.get(f"/targets/{object_id}/summary", params={"project": "SP_CLO"}).json()["totals"]
    stats = client.get("/catalog/analysis-stats", params=[("pair", "SP_CLO:CM_PAR_LOAN_TRADES")]).json()
    assert stats["target_columns"] == totals["columns"]
    assert stats["target_columns_with_lineage"] == totals["with_lineage"]
    assert stats["business_processes"] > 0
    assert stats["components"] > 0
    assert stats["mappings"] > 0
    assert stats["lineage_paths"] > 0


def test_stats_sum_across_projects(outputs):
    liq = ROOT / "outputs" / "SP_LIQ" / "lineage.db"
    if not liq.is_file():
        pytest.skip("SP_LIQ lineage DB required")
    folder = outputs / "SP_LIQ"
    folder.mkdir()
    shutil.copy(liq, folder / "lineage.db")
    client = TestClient(create_app(outputs_dir=str(outputs)))
    clo_only = client.get("/catalog/analysis-stats", params=[("pair", "SP_CLO:CM_PAR_LOAN_TRADES")]).json()
    liq_only = client.get("/catalog/analysis-stats", params=[("pair", "SP_LIQ:PAR_GFRS_LIQ_TRADES")]).json()
    both = client.get(
        "/catalog/analysis-stats",
        params=[("pair", "SP_CLO:CM_PAR_LOAN_TRADES"), ("pair", "SP_LIQ:PAR_GFRS_LIQ_TRADES")],
    ).json()
    for field in both:
        assert both[field] == clo_only[field] + liq_only[field]


def test_unknown_tables_contribute_nothing(outputs):
    client = TestClient(create_app(outputs_dir=str(outputs)))
    stats = client.get("/catalog/analysis-stats", params=[("pair", "SP_CLO:NO_SUCH_TABLE")]).json()
    assert all(value == 0 for value in stats.values())


def test_no_pairs_is_all_zero(outputs):
    client = TestClient(create_app(outputs_dir=str(outputs)))
    stats = client.get("/catalog/analysis-stats").json()
    assert all(value == 0 for value in stats.values())
