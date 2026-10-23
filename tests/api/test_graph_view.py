import shutil
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT

sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.app import create_app  # noqa: E402
from lineage_api.lineage_graph import build_target_graph  # noqa: E402
from lineage_api.migrations import add_business_process_columns  # noqa: E402
from lineage_api.target_catalog import list_target_columns, summarize_target, target_definitions  # noqa: E402


@pytest.fixture()
def db_file(lineage_db_path, tmp_path):
    target = tmp_path / "lineage.db"
    shutil.copy(lineage_db_path, target)
    c = sqlite3.connect(target)
    add_business_process_columns(c)
    c.close()
    return target


@pytest.fixture()
def real(db_file):
    c = sqlite3.connect(db_file)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture()
def sp_clo(real, lineage_db_path):
    if lineage_db_path.parent.name != "SP_CLO":
        pytest.skip("SP_CLO-specific expectations")
    return real


def _table(conn, name, source_project=None):
    obj = next(
        o for o in target_definitions(conn, "SP_CLO")
        if o["object_name"] == name and (source_project is None or o["source_project"] == source_project)
    )
    return obj["object_id"], summarize_target(conn, "SP_CLO", obj["object_id"])


def _column(summary, name):
    return next(c for c in summary["columns"] if c["column_name"] == name)


def _graph(conn, name, column):
    object_id, summary = _table(conn, name)
    col = _column(summary, column)
    return build_target_graph(conn, "SP_CLO", object_id, col["column_id"]), col


def test_graph_of_a_direct_mapping_is_target_to_source(sp_clo):
    g, col = _graph(sp_clo, "PAR_GFRS_CLO_TRADES", "OFR_ACCEPTANCE_DATE")
    assert g["has_lineage"]
    assert [n["role"] for n in g["nodes"]] == ["target", "source"]
    assert len(g["edges"]) == 1
    edge = g["edges"][0]
    assert edge["from_node"] == "target" and edge["hop"] == 1
    assert edge["to_node"] == g["nodes"][1]["node_id"]
    assert g["totals"] == {"nodes": 2, "edges": 1, "sources": 1, "hops_max": 1}


def test_graph_sources_and_hops_agree_with_the_summary(sp_clo):
    for table in ("CM_PAR_LOAN_TRADES", "AR_PAR_LOAN_EVENTS"):
        object_id, summary = _table(sp_clo, table)
        for col in summary["columns"]:
            if not col["has_lineage"]:
                continue
            g = build_target_graph(sp_clo, "SP_CLO", object_id, col["column_id"])
            sources = [n for n in g["nodes"] if n["role"] == "source"]
            got = sorted((n["object_name"], n["column_name"], n["condition"] or "", n["hops_min"], n["hops_max"], n["kind"]) for n in sources)
            want = sorted(
                (s["object_name"], s["column_name"], s["condition"] or "", s["hops_min"], s["hops_max"], s["kind"])
                for s in col["sources"]
            )
            assert got == want, f"{table}.{col['column_name']}"


def test_graph_is_connected_downwards_from_the_target(sp_clo):
    object_id, summary = _table(sp_clo, "CM_PAR_LOAN_TRADES")
    for col in summary["columns"]:
        if not col["has_lineage"]:
            continue
        g = build_target_graph(sp_clo, "SP_CLO", object_id, col["column_id"])
        ids = {n["node_id"] for n in g["nodes"]}
        assert len(ids) == len(g["nodes"])
        assert all(e["from_node"] in ids and e["to_node"] in ids for e in g["edges"])
        seen, stack = set(), ["target"]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(e["to_node"] for e in g["edges"] if e["from_node"] == cur)
        assert seen == ids, col["column_name"]
        assert all(e["from_node"] != "target" or e["hop"] == 1 for e in g["edges"])


def test_shared_upstream_is_one_node_with_several_incoming_edges(sp_clo):
    g, col = _graph(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    assert col["source_count"] == 3
    middles = [n for n in g["nodes"] if n["role"] == "intermediate"]
    assert middles
    # 3 sources x 2 routes each, but the shared middle steps are drawn once
    assert len(g["edges"]) < 3 * 2 * 4
    assert g["totals"]["hops_max"] == 4
    incoming = {}
    for e in g["edges"]:
        incoming[e["to_node"]] = incoming.get(e["to_node"], 0) + 1
    assert any(n > 1 for n in incoming.values())


def test_case_branches_to_one_constant_are_separate_source_nodes(sp_clo):
    g, _ = _graph(sp_clo, "AR_PAR_LOAN_EVENTS", "PDT_CODE")
    sources = [n for n in g["nodes"] if n["role"] == "source"]
    assert sorted(n["condition"] for n in sources) == ['AEF_EVENT_CODE=="E011"', "ELSE"]
    assert all(n["kind"] == "constant" for n in sources)
    by_node = {n["node_id"]: n for n in g["nodes"]}
    into_sources = [e for e in g["edges"] if by_node[e["to_node"]]["role"] == "source"]
    assert sorted(e["condition"] for e in into_sources) == ['AEF_EVENT_CODE=="E011"', "ELSE"]


def test_edges_carry_relation_ids_and_steps(sp_clo):
    g, _ = _graph(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    for e in g["edges"]:
        assert e["relation_id"] and e["step_ids"] and e["relation_type"]
        assert sp_clo.execute("SELECT 1 FROM column_relation WHERE relation_id = ?", (e["relation_id"],)).fetchone()


def test_column_without_lineage_gives_an_empty_graph(sp_clo):
    object_id, summary = _table(sp_clo, "CM_PAR_LOAN_TRADES")
    none = next((c for c in summary["columns"] if not c["has_lineage"]), None)
    if none is None:
        pytest.skip("every column has lineage")
    g = build_target_graph(sp_clo, "SP_CLO", object_id, none["column_id"])
    assert g["has_lineage"] is False and g["nodes"] == [] and g["edges"] == []


def test_graph_endpoint(db_file, sp_clo):
    object_id, summary = _table(sp_clo, "CM_PAR_LOAN_TRADES")
    col = _column(summary, "FDK_MT")
    client = TestClient(create_app(str(db_file)))
    r = client.get("/lineage/graph", params={"project": "SP_CLO", "object_id": object_id, "column_id": col["column_id"]})
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["sources"] == 3 and body["nodes"][0]["role"] == "target"
    assert client.get("/lineage/graph", params={"project": "SP_CLO", "object_id": object_id, "column_id": "nope"}).status_code == 404
    assert client.get("/lineage/graph", params={"project": "SP_CLO"}).status_code == 422
