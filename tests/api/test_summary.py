import shutil
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT

sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.app import create_app  # noqa: E402
from lineage_api.catalog import list_target_columns, list_target_objects, search_target_objects  # noqa: E402
from lineage_api.migrations import add_business_process_columns  # noqa: E402
from lineage_api.sources import _terminal_id, resolve_terminal_sources  # noqa: E402
from lineage_api.summary import TableSummaryCache, source_kind, summarize_table  # noqa: E402
from lineage_api.upstream import get_root_choices, get_upstream_choices  # noqa: E402


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


def _object(conn, name, source_project="SP_CLO"):
    return next(
        o for o in list_target_objects(conn, "SP_CLO")
        if o["object_name"] == name and o["source_project"] == source_project
    )


def _columns(conn, name):
    summary = summarize_table(conn, "SP_CLO", _object(conn, name)["object_id"])
    return {c["column_name"]: c for c in summary["columns"]}


def _routes(conn, project, object_id, column_id):
    """Oracle: every route to a leaf, walked with the upstream service; yields (terminal_id, hops)."""
    out = []

    def walk(choices, depth):
        for c in choices:
            kids = get_upstream_choices(conn, c["step_id"])
            if not kids:
                tid = f"{c['source_object_id']}|{c['source_column_id']}"
                if c["driving_expression"] is not None or c["result_expression"] is not None:
                    tid += f"|{c['driving_expression'] or ''}|{c['result_expression'] or ''}"
                out.append((tid, depth))
            else:
                walk(kids, depth + 1)

    walk(get_root_choices(conn, project, object_id, column_id), 1)
    return out


# --- search -----------------------------------------------------------------------------------------

def test_search_without_text_lists_every_target_object(sp_clo):
    assert search_target_objects(sp_clo, "SP_CLO", "") == list_target_objects(sp_clo, "SP_CLO")
    assert search_target_objects(sp_clo, "SP_CLO", "   ") == list_target_objects(sp_clo, "SP_CLO")


def test_search_matches_part_of_a_name_ignoring_case(sp_clo):
    assert [o["object_name"] for o in search_target_objects(sp_clo, "SP_CLO", "gfrs")] == ["PAR_GFRS_CLO_TRADES"]
    names = [o["object_name"] for o in search_target_objects(sp_clo, "SP_CLO", "Unprocessed")]
    assert names == ["PAR_UNPROCESSED_EVENTS"] * 2 + ["PAR_UNPROCESSED_TRADES"] * 2
    assert search_target_objects(sp_clo, "SP_CLO", "loan") != []
    assert search_target_objects(sp_clo, "SP_CLO", "no_such_table") == []


def test_search_keeps_same_named_objects_apart(sp_clo):
    found = search_target_objects(sp_clo, "SP_CLO", "PAR_UNPROCESSED_EVENTS")
    assert {o["source_project"] for o in found} == {"SP_CLO", "GP_SHARED"}
    assert len({o["object_id"] for o in found}) == 2


# --- summary content on the real data ------------------------------------------------------------------

def test_every_declared_column_is_listed_in_name_order(sp_clo):
    for o in list_target_objects(sp_clo, "SP_CLO"):
        summary = summarize_table(sp_clo, "SP_CLO", o["object_id"])
        names = [c["column_name"] for c in summary["columns"]]
        assert names == sorted(names)
        assert names == [c["column_name"] for c in list_target_columns(sp_clo, "SP_CLO", o["object_id"])]
        assert summary["totals"] == {"columns": len(names), "with_lineage": len(names)}


def test_summary_matches_an_independent_walk_of_every_route(sp_clo):
    for o in list_target_objects(sp_clo, "SP_CLO"):
        summary = summarize_table(sp_clo, "SP_CLO", o["object_id"])
        for col in summary["columns"]:
            expected = {}
            for tid, hops in _routes(sp_clo, "SP_CLO", o["object_id"], col["column_id"]):
                lo, hi, n = expected.get(tid, (hops, hops, 0))
                expected[tid] = (min(lo, hops), max(hi, hops), n + 1)
            got = {s["terminal_id"]: (s["hops_min"], s["hops_max"], s["route_count"]) for s in col["sources"]}
            assert got == expected, (o["object_name"], col["column_name"])


def test_summary_sources_equal_the_ultimate_source_resolver(sp_clo):
    for o in list_target_objects(sp_clo, "SP_CLO"):
        for col in summarize_table(sp_clo, "SP_CLO", o["object_id"])["columns"]:
            resolved = resolve_terminal_sources(sp_clo, "SP_CLO", o["object_id"], col["column_id"])
            assert [s["terminal_id"] for s in col["sources"]] == [t["terminal_id"] for t in resolved["terminal_sources"]]


def test_column_totals_follow_from_its_sources(sp_clo):
    for o in list_target_objects(sp_clo, "SP_CLO"):
        for col in summarize_table(sp_clo, "SP_CLO", o["object_id"])["columns"]:
            sources = col["sources"]
            assert col["source_count"] == len(sources) > 0
            assert col["hops_min"] == min(s["hops_min"] for s in sources)
            assert col["hops_max"] == max(s["hops_max"] for s in sources)
            for s in sources:
                assert 1 <= s["hops_min"] <= s["hops_max"]
                assert s["route_count"] >= 1


def test_each_route_runs_from_the_first_mapping_to_its_source_in_the_fewest_hops(sp_clo):
    for o in list_target_objects(sp_clo, "SP_CLO"):
        for col in summarize_table(sp_clo, "SP_CLO", o["object_id"])["columns"]:
            for s in col["sources"]:
                assert len(s["route"]) == s["hops_min"]
                assert s["route"][-1]["endpoint"] == f'{s["object_name"]}.{s["column_name"]}'


def test_a_direct_mapping_is_one_hop(sp_clo):
    col = _columns(sp_clo, "PAR_GFRS_CLO_TRADES")["OFR_ACCEPTANCE_DATE"]
    assert (col["source_count"], col["hops_min"], col["hops_max"]) == (1, 1, 1)
    (source,) = col["sources"]
    assert source["kind"] == "column"
    assert source["route"] == [
        {"endpoint": "CM_CLO_OFFER.OFR_ACCEPTANCE_DATE", "relation_type": "AUTO_MAP_BY_NAME",
         "component_name": "CM_CLO_OFR GFRS Mapping"},
    ]


def test_fdk_mt_has_three_sources_four_hops_each(sp_clo):
    col = _columns(sp_clo, "CM_PAR_LOAN_TRADES")["FDK_MT"]
    assert [s["column_name"] for s in col["sources"]] == ["OFR_HTCS_BOOK_CODE", "OFR_HTC_BOOK_CODE", "OFR_HTS_BOOK_CODE"]
    assert (col["hops_min"], col["hops_max"]) == (4, 4)
    first = col["sources"][0]
    assert [r["endpoint"] for r in first["route"]] == [
        "CM_CLO_OFFER.e_fdk_mt", "FSD_FO_DESKS.FDK_MT", "CM_CLO_OFFER.e_bok_code", "CM_CLO_OFFER.OFR_HTCS_BOOK_CODE",
    ]
    assert [r["relation_type"] for r in first["route"]] == [
        "EXPLICIT_INATTR", "EXPLICIT_PATHFROM_PATHTO", "ENRICHMENT_LOOKUP", "EXPLICIT_INATTR",
    ]
    assert first["route_count"] == 1  # both mappings (COMM and Fair Value) merge into one path
    assert col["flags"] == {"constant": False, "function": False, "not_persisted": False,
                            "case_branches": False, "inferred": False}


def test_contract_id_counts_all_routes_into_the_one_source(sp_clo):
    col = _columns(sp_clo, "CM_PAR_LOAN_TRADES")["CONTRACT_ID"]
    (source,) = col["sources"]
    assert (source["object_name"], source["column_name"]) == ("CM_CLO_OFFER", "OFR_ID")
    assert (source["hops_min"], source["hops_max"]) == (2, 2)
    assert source["route_count"] == 1  # the 2 mappings x 3 rule calls merge into one path


def test_case_branches_to_one_constant_stay_separate_with_their_conditions(sp_clo):
    col = _columns(sp_clo, "AR_PAR_LOAN_EVENTS")["PDT_CODE"]
    assert [(s["kind"], s["condition"], s["result_expression"]) for s in col["sources"]] == [
        ("constant", 'AEF_EVENT_CODE=="E011"', '"OFFER"'),
        ("constant", "ELSE", '"OFFER"'),
    ]
    assert (col["hops_min"], col["hops_max"]) == (2, 2)
    assert col["flags"]["case_branches"] is True and col["flags"]["constant"] is True


def test_constants_functions_and_not_persisted_are_classified(sp_clo):
    cols = _columns(sp_clo, "CM_PAR_LOAN_TRADES")
    assert [s["kind"] for s in cols["TRADE_STATUS"]["sources"]] == ["constant"]
    assert cols["TRADE_STATUS"]["flags"]["constant"] is True
    assert [s["kind"] for s in cols["PAR_TIMESTAMP"]["sources"]] == ["function"]
    assert cols["PAR_TIMESTAMP"]["flags"]["function"] is True
    assert [s["kind"] for s in cols["END_DATE"]["sources"]] == ["not_persisted"]
    assert cols["END_DATE"]["flags"]["not_persisted"] is True
    assert cols["END_DATE"]["flags"]["inferred"] is True


def test_source_kind_rules():
    assert source_kind("DataObject", ["EXPLICIT_INATTR"]) == "column"
    assert source_kind("CONSTANT", ["EXPRESSION"]) == "constant"
    assert source_kind("DataObject", ["CONSTANT_ASSIGNMENT"]) == "constant"
    assert source_kind("DataObject", ["RUNTIME_FUNCTION_ASSIGNMENT"]) == "function"
    assert source_kind("Synthetic", ["NOT_PERSISTED"]) == "not_persisted"
    assert source_kind(None, []) == "column"


def test_terminal_flag_is_honoured_like_everywhere_else(sp_clo):
    obj = _object(sp_clo, "CM_PAR_LOAN_TRADES")
    column = next(c for c in list_target_columns(sp_clo, "SP_CLO", obj["object_id"]) if c["column_name"] == "FDK_MT")
    for root in get_root_choices(sp_clo, "SP_CLO", obj["object_id"], column["column_id"]):
        sp_clo.execute("UPDATE business_lineage_step SET is_terminal = 1 WHERE step_id = ?", (root["step_id"],))
    col = _columns(sp_clo, "CM_PAR_LOAN_TRADES")["FDK_MT"]
    assert [(s["column_name"], s["hops_min"]) for s in col["sources"]] == [("e_fdk_mt", 1)]


def test_columns_without_any_lineage_are_listed_and_marked(sp_clo):
    obj = _object(sp_clo, "CM_PAR_LOAN_TRADES")
    sp_clo.execute(
        "INSERT INTO canonical_column (column_id, object_id, column_name, declared_type, is_declared, is_inferred)"
        " VALUES ('COL_orphan', ?, 'AAA_NO_LINEAGE', NULL, 1, 0)",
        (obj["object_id"],),
    )
    # An EDF-backed database marks all of the object's columns as declared.
    sp_clo.execute("UPDATE canonical_column SET is_declared=1, is_inferred=0 WHERE object_id=?", (obj["object_id"],))
    summary = summarize_table(sp_clo, "SP_CLO", obj["object_id"])
    assert summary["totals"] == {"columns": 27, "with_lineage": 26}
    orphan = summary["columns"][0]
    assert orphan["column_name"] == "AAA_NO_LINEAGE"
    assert orphan["has_lineage"] is False
    assert (orphan["source_count"], orphan["hops_min"], orphan["hops_max"], orphan["sources"]) == (0, None, None, [])
    assert not any(orphan["flags"].values())
    assert all(c["has_lineage"] for c in summary["columns"][1:])


def test_summary_is_deterministic_and_json_serialisable(sp_clo):
    import json
    obj = _object(sp_clo, "AR_PAR_LOAN_EVENTS")
    first = summarize_table(sp_clo, "SP_CLO", obj["object_id"])
    assert first == summarize_table(sp_clo, "SP_CLO", obj["object_id"])
    json.dumps(first)


# --- cache and HTTP ----------------------------------------------------------------------------------------

@pytest.fixture()
def client(db_file, lineage_db_path):
    if lineage_db_path.parent.name != "SP_CLO":
        pytest.skip("SP_CLO-specific expectations")
    return TestClient(create_app(str(db_file)))


def _error(response):
    body = response.json()
    assert set(body) == {"error"}
    return body["error"]["code"]


def _events(client):
    return next(o for o in client.get("/targets", params={"project": "SP_CLO"}).json()
                if o["object_name"] == "AR_PAR_LOAN_EVENTS")


def test_search_endpoint(client):
    r = client.get("/targets/search", params={"project": "SP_CLO", "q": "loan"})
    assert r.status_code == 200
    assert [o["object_name"] for o in r.json()] == ["AR_PAR_LOAN_EVENTS", "CM_PAR_LOAN_TRADES"]
    assert set(r.json()[0]) == {"object_id", "object_name", "source_project", "business_processes", "column_count"}
    assert len(client.get("/targets/search", params={"project": "SP_CLO"}).json()) == 5
    assert client.get("/targets/search", params={"project": "SP_CLO", "q": "zzz"}).json() == []


def test_search_endpoint_errors(client):
    r = client.get("/targets/search", params={"project": "NOPE", "q": "a"})
    assert r.status_code == 404 and _error(r) == "PROJECT_NOT_FOUND"
    r = client.get("/targets/search")
    assert r.status_code == 422 and _error(r) == "VALIDATION_ERROR"


def test_summary_endpoint_returns_the_table_and_its_columns(client):
    obj = _events(client)
    r = client.get(f"/targets/{obj['object_id']}/summary", params={"project": "SP_CLO"})
    assert r.status_code == 200
    body = r.json()
    assert body["object"]["object_name"] == "AR_PAR_LOAN_EVENTS"
    assert body["totals"] == {"columns": 46, "with_lineage": 46}
    pdt = next(c for c in body["columns"] if c["column_name"] == "PDT_CODE")
    assert set(pdt) == {"column_id", "column_name", "has_lineage", "source_count", "hops_min", "hops_max", "flags", "sources"}
    assert [s["condition"] for s in pdt["sources"]] == ['AEF_EVENT_CODE=="E011"', "ELSE"]
    assert set(pdt["sources"][0]) == {
        "terminal_id", "object_name", "column_name", "object_type", "kind", "condition", "result_expression",
        "leaf_relation_types", "hops_min", "hops_max", "route_count", "route",
    }
    assert {s["kind"] for c in body["columns"] for s in c["sources"]} <= {"column", "constant", "function", "not_persisted"}


def test_summary_endpoint_errors(client):
    obj = _events(client)
    r = client.get("/targets/OBJ_nope/summary", params={"project": "SP_CLO"})
    assert r.status_code == 404 and _error(r) == "TARGET_OBJECT_NOT_FOUND"
    r = client.get(f"/targets/{obj['object_id']}/summary", params={"project": "NOPE"})
    assert r.status_code == 404 and _error(r) == "PROJECT_NOT_FOUND"
    r = client.get(f"/targets/{obj['object_id']}/summary")
    assert r.status_code == 422 and _error(r) == "VALIDATION_ERROR"


def test_summary_is_cached_until_the_database_changes(client, db_file):
    obj = _events(client)
    url, params = f"/targets/{obj['object_id']}/summary", {"project": "SP_CLO"}
    first = client.get(url, params=params).json()
    for _ in range(3):
        assert client.get(url, params=params).json() == first
    assert client.app.state.summary_cache.compute_count == 1

    rw = sqlite3.connect(db_file)
    rw.execute("UPDATE business_lineage_step SET is_terminal = 1 WHERE lineage_level = 0")
    rw.commit()
    rw.close()
    changed = client.get(url, params=params).json()
    assert client.app.state.summary_cache.compute_count == 2
    assert changed != first
    pdt = next(c for c in changed["columns"] if c["column_name"] == "PDT_CODE")
    assert [s["hops_max"] for s in pdt["sources"]] == [1]


def test_cache_keeps_tables_apart_and_is_bounded(real, lineage_db_path):
    if lineage_db_path.parent.name != "SP_CLO":
        pytest.skip("SP_CLO-specific expectations")
    cache = TableSummaryCache(max_entries=2)
    ids = [o["object_id"] for o in list_target_objects(real, "SP_CLO")[:3]]
    for i in ids:
        cache.get(real, "SP_CLO", i)
    assert cache.compute_count == 3
    cache.get(real, "SP_CLO", ids[2])
    cache.get(real, "SP_CLO", ids[1])
    assert cache.compute_count == 3
    cache.get(real, "SP_CLO", ids[0])
    assert cache.compute_count == 4
