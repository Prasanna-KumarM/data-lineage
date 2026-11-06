import shutil
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT

sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.app import create_app  # noqa: E402

SP_CLO = ROOT / "outputs" / "SP_CLO" / "lineage.db"


@pytest.fixture()
def outputs(tmp_path):
    if not SP_CLO.is_file():
        pytest.skip("SP_CLO lineage DB required")
    folder = tmp_path / "SP_CLO"
    folder.mkdir()
    shutil.copy(SP_CLO, folder / "lineage.db")
    return tmp_path


def write_catalog(tmp_path, rows):
    path = tmp_path / "catalog.csv"
    path.write_text("project,value_chain,source_system,target_system,tables\n" + "\n".join(rows) + "\n")
    return path


def client_for(outputs, catalog):
    return TestClient(create_app(outputs_dir=str(outputs), catalog_path=str(catalog)))


def test_projects_entries_gain_the_business_mapping(outputs, tmp_path):
    catalog = write_catalog(tmp_path, ["SP_CLO,Lending,CLO,GFRS,PAR_GFRS_CLO_TRADES"])
    entry = client_for(outputs, catalog).get("/projects").json()[0]
    assert entry["value_chain"] == "Lending"
    assert entry["source_system"] == "CLO"
    assert entry["target_system"] == "GFRS"
    assert entry["business_tables"] == ["PAR_GFRS_CLO_TRADES"]
    assert "catalog_notes" not in entry


def test_unknown_catalog_table_is_called_out(outputs, tmp_path):
    catalog = write_catalog(tmp_path, ["SP_CLO,Lending,CLO,GFRS,PAR_GFRS_CLO_TRADES|NO_SUCH_TABLE"])
    entry = client_for(outputs, catalog).get("/projects").json()[0]
    assert entry["catalog_notes"] == ["Catalog table NO_SUCH_TABLE was not found in SP_CLO."]


def test_catalog_row_without_database_becomes_a_ghost_entry(outputs, tmp_path):
    catalog = write_catalog(
        tmp_path,
        ["SP_CLO,Lending,CLO,GFRS,PAR_GFRS_CLO_TRADES", "SP_TFS_TIP,Trade Finance,Ti Plus,GFRS,PAR_GFRS_TFS_TRADES"],
    )
    entries = client_for(outputs, catalog).get("/projects").json()
    ghost = next(e for e in entries if e["project_name"] == "SP_TFS_TIP")
    assert ghost["ready"] is False and ghost["startable"] is False
    assert "no database" in ghost["problem"]
    assert ghost["value_chain"] == "Trade Finance"


def test_ready_project_without_catalog_row_is_noted(outputs, tmp_path):
    catalog = write_catalog(tmp_path, ["SP_OTHER,Lending,X,GFRS,T"])
    entries = client_for(outputs, catalog).get("/projects").json()
    entry = next(e for e in entries if e["project_name"] == "SP_CLO")
    assert "value_chain" not in entry
    assert entry["catalog_notes"] == ["SP_CLO has no catalog entry; it only shows in the developer view."]


def test_no_catalog_file_changes_nothing(outputs):
    client = TestClient(create_app(outputs_dir=str(outputs), catalog_path=str(outputs / "none.csv")))
    assert client.get("/projects").json() == [{"project_name": "SP_CLO", "folder": "SP_CLO"}]


def test_catalog_reloads_when_the_file_changes(outputs, tmp_path):
    catalog = write_catalog(tmp_path, ["SP_CLO,Lending,CLO,GFRS,PAR_GFRS_CLO_TRADES"])
    client = client_for(outputs, catalog)
    assert client.get("/projects").json()[0]["value_chain"] == "Lending"
    write_catalog(tmp_path, ["SP_CLO,Markets,CLO,GFRS,PAR_GFRS_CLO_TRADES"])
    assert client.get("/projects").json()[0]["value_chain"] == "Markets"
