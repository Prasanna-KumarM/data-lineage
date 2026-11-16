import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT

import sys
sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.app import create_app  # noqa: E402
from lineage_api.target_catalog import list_target_columns, summarize_target, target_column_pairs, target_definitions  # noqa: E402
from lineage_api.upstream import get_root_choices  # noqa: E402


@pytest.fixture()
def sp_liq_db():
    path = ROOT / "outputs" / "SP_LIQ" / "lineage.db"
    if not path.is_file():
        pytest.skip("SP_LIQ lineage DB is not available")
    return path


def test_sp_liq_catalog_uses_aptitude_target_components(sp_liq_db):
    client = TestClient(create_app(str(sp_liq_db)))
    response = client.get("/targets", params={"project": "SP_LIQ"})
    assert response.status_code == 200
    targets = response.json()
    assert len(targets) == 11
    assert len({t["object_name"] for t in targets}) == 11
    fee = next(t for t in targets if t["object_name"] == "CM_PAR_FEE_TRADES")
    assert fee["source_project"] == "GP_SHARED"
    assert {p["business_process_name"] for p in fee["business_processes"]} == {
        "CM_LIQ_AMRT_ADMIN_FEE",
        "CM_LIQ_DELAYED_COMP_ITEMS",
        "CM_LIQ_PORTF_ACCRUAL",
        "CM_LIQ_PORTF_COMMIT_SHARE",
    }


def test_walkthrough_choices_start_only_from_target_owned_business_processes(sp_liq_db):
    client = TestClient(create_app(str(sp_liq_db)))
    target = next(
        t for t in client.get("/targets", params={"project": "SP_LIQ"}).json()
        if t["object_name"] == "CM_PAR_FEE_TRADES"
    )
    summary = client.get(
        f"/targets/{target['object_id']}/summary", params={"project": "SP_LIQ"}
    ).json()
    column = next(c for c in summary["columns"] if c["column_name"] == "CONTRACT_ID")
    response = client.get(
        "/lineage/upstream",
        params={"project": "SP_LIQ", "object_id": target["object_id"], "column_id": column["column_id"]},
    )
    assert response.status_code == 200
    choices = response.json()["choices"]
    assert choices
    allowed = {p["business_process_name"] for p in target["business_processes"]}
    assert {choice["business_process_name"] for choice in choices} <= allowed
    assert len(choices) == 10
    assert "CM_LIQ_DELAYED_COMP_ITEMS" in {choice["business_process_name"] for choice in choices}


def test_summary_and_graph_use_the_target_union_not_an_intermediate_root(sp_liq_db):
    client = TestClient(create_app(str(sp_liq_db)))
    target = next(
        t for t in client.get("/targets", params={"project": "SP_LIQ"}).json()
        if t["object_name"] == "CM_PAR_FEE_TRADES"
    )
    summary = client.get(
        f"/targets/{target['object_id']}/summary", params={"project": "SP_LIQ"}
    ).json()
    assert summary["totals"] == {"columns": 27, "with_lineage": 27}
    contract = next(c for c in summary["columns"] if c["column_name"] == "CONTRACT_ID")
    graph = client.get(
        "/lineage/graph",
        params={"project": "SP_LIQ", "object_id": target["object_id"], "column_id": contract["column_id"]},
    )
    assert graph.status_code == 200
    body = graph.json()
    assert body["nodes"][0]["role"] == "target"
    assert body["nodes"][0]["object_name"] == "CM_PAR_FEE_TRADES"
    assert body["totals"]["sources"] == 4
    assert body["totals"]["edges"] == 26


def test_cm_par_sap_trades_keeps_all_twenty_wip_sap_relations(sp_liq_db):
    conn = sqlite3.connect(f"file:{sp_liq_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    target = next(t for t in target_definitions(conn, "SP_LIQ") if t["object_name"] == "CM_PAR_SAP_TRADES")
    assert len(target["_root_pairs"]) == 2
    columns = list_target_columns(conn, "SP_LIQ", target["object_id"])
    assert len(columns) == 19

    component = conn.execute(
        """SELECT component_id,business_process_id FROM component
           WHERE component_name='CM_LIQ_WIP_SAP Mapping' AND component_type='AptitudeServiceRuleCall'"""
    ).fetchone()
    relation_ids = {
        row[0] for row in conn.execute(
            "SELECT relation_id FROM column_relation WHERE component_id=? AND target_object_id IN (?,?)",
            (component["component_id"], *(root_id for _, root_id in target["_root_pairs"])),
        )
    }
    step_ids = {
        row[0] for row in conn.execute(
            """SELECT relation_id FROM business_lineage_step
               WHERE component_id=? AND business_process_id=? AND lineage_level=0
                 AND root_target_object_name='CM_PAR_SAP_TRADES'""",
            (component["component_id"], component["business_process_id"]),
        )
    }
    assert len(relation_ids) == 20
    assert step_ids == relation_ids

    choices = []
    for column in columns:
        for bp_id, root_id, root_column_id in target_column_pairs(
            conn, "SP_LIQ", target["object_id"], column["column_id"]
        ):
            choices.extend(get_root_choices(conn, "SP_LIQ", root_id, root_column_id, bp_id))
    assert len(choices) == 20
    conn.close()

def test_target_from_directly_invoked_project_is_included_in_selected_project_db(sp_liq_db, tmp_path):
    import shutil

    copy = tmp_path / "lineage.db"
    shutil.copy(sp_liq_db, copy)
    conn = sqlite3.connect(copy)
    conn.row_factory = sqlite3.Row
    target_component = conn.execute(
        """SELECT t.component_id,t.business_process_id,t.local_block_id,t.referenced_element_name,
                         t.referenced_project_name,bp.business_process_name
           FROM component t JOIN business_process bp ON bp.business_process_id=t.business_process_id
           WHERE bp.project_name='SP_LIQ' AND t.component_type='AptitudeServiceTarget'
             AND t.referenced_element_type='Target' AND t.referenced_element_name='AR_PAR_FEE_EVENTS'
             AND t.referenced_project_name='GP_SHARED'"""
    ).fetchone()
    assert target_component is not None
    caller_id = target_component["business_process_id"]
    shared_id = "BPR_TEST_GP_SHARED_FEE_EVENTS"
    shared_name = "AR_PAR_FEE_EVENTS Shared"
    call_component_id = "CMP_TEST_GP_SHARED_FEE_EVENTS_CALL"
    conn.execute(
        "INSERT INTO business_process (business_process_id,project_name,business_process_name) VALUES (?,?,?)",
        (shared_id, "GP_SHARED", shared_name),
    )
    conn.execute(
        "UPDATE component SET business_process_id=? WHERE component_id=?",
        (shared_id, target_component["component_id"]),
    )
    conn.execute(
        """INSERT INTO component (
               component_id,business_process_id,local_block_id,component_type,component_name,
               is_active,is_visible,referenced_element_type,referenced_element_name,referenced_project_name
           ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            call_component_id,
            caller_id,
            "LOCAL_TEST_GP_SHARED_FEE_EVENTS_CALL",
            "AptitudeServiceBlock",
            "Call shared fee events",
            1,
            1,
            "BusinessProcess",
            shared_name,
            "GP_SHARED",
        ),
    )
    conn.execute(
        """INSERT INTO business_process_invocation (
               invocation_id,calling_business_process_id,call_component_id,
               referenced_business_process_name,referenced_project_name,
               referenced_business_process_id,resolution_status
           ) VALUES (?,?,?,?,?,?,?)""",
        (
            "INV_TEST_GP_SHARED_FEE_EVENTS",
            caller_id,
            call_component_id,
            shared_name,
            "GP_SHARED",
            shared_id,
            "RESOLVED",
        ),
    )
    conn.commit()
    conn.close()

    client = TestClient(create_app(str(copy)))
    response = client.get("/targets", params={"project": "SP_LIQ"})
    assert response.status_code == 200
    target = next(
        item for item in response.json()
        if item["object_name"] == "AR_PAR_FEE_EVENTS" and item["source_project"] == "GP_SHARED"
    )
    assert {p["business_process_name"] for p in target["business_processes"]} == {
        "AR_LIQ_EVENT_PROCESSING",
        shared_name,
    }
    summary = client.get(f"/targets/{target['object_id']}/summary", params={"project": "SP_LIQ"})
    assert summary.status_code == 200
    assert summary.json()["totals"]["with_lineage"] > 0


def test_gfrs_target_includes_lineage_from_its_block_callers(sp_liq_db):
    conn = sqlite3.connect(f"file:{sp_liq_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    target = next(t for t in target_definitions(conn, "SP_LIQ") if t["object_name"] == "PAR_GFRS_LIQ_TRADES")
    assert len(target["business_processes"]) == 13
    summary = summarize_target(conn, "SP_LIQ", target["object_id"])
    assert summary["totals"] == {"columns": 226, "with_lineage": 226}
    adjusted_amount = next(c for c in summary["columns"] if c["column_name"] == "ACC_AMT_ADJ")
    assert adjusted_amount["has_lineage"] is True
    assert adjusted_amount["source_count"] == 7
    assert adjusted_amount["hops_min"] == adjusted_amount["hops_max"] == 1
    conn.close()


def test_only_declared_columns_of_a_root_object_are_listed(sp_liq_db, tmp_path):
    import shutil

    copy = tmp_path / "lineage.db"
    shutil.copy(sp_liq_db, copy)
    conn = sqlite3.connect(copy)
    conn.row_factory = sqlite3.Row
    target = next(t for t in target_definitions(conn, "SP_LIQ") if t["object_name"] == "PAR_GFRS_LIQ_TRADES")
    all_names = [c["column_name"] for c in list_target_columns(conn, "SP_LIQ", target["object_id"])]
    assert len(all_names) == 226 and target["column_count"] == 226

    interim = [n for n in all_names if n.startswith("e_")]
    conn.execute(
        "UPDATE canonical_column SET is_declared=1, is_inferred=0 WHERE object_id IN "
        "(SELECT object_id FROM canonical_object WHERE object_name='PAR_GFRS_LIQ_TRADES') "
        f"AND column_name NOT IN ({','.join('?' for _ in interim)})",
        interim,
    )
    conn.commit()

    target = next(t for t in target_definitions(conn, "SP_LIQ") if t["object_name"] == "PAR_GFRS_LIQ_TRADES")
    names = [c["column_name"] for c in list_target_columns(conn, "SP_LIQ", target["object_id"])]
    assert target["column_count"] == 226 - len(interim)
    assert names == [n for n in all_names if n not in interim]
    summary = summarize_target(conn, "SP_LIQ", target["object_id"])
    assert [c["column_name"] for c in summary["columns"]] == [n for n in all_names if n not in interim]

    other = next(t for t in target_definitions(conn, "SP_LIQ") if t["object_name"] == "CM_PAR_LOAN_TRADES")
    assert other["column_count"] == 42
