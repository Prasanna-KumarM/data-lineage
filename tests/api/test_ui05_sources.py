import os
import shutil
import sqlite3
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "api"))

from lineage_api.catalog import list_target_columns, list_target_objects  # noqa: E402
from lineage_api.migrations import add_business_process_columns  # noqa: E402
from lineage_api.sources import (  # noqa: E402
    TargetSourceCache,
    resolve_terminal_sources,
    sources_for_step,
)
from lineage_api.upstream import (  # noqa: E402
    StepNotFound,
    get_root_choices,
    get_upstream_choices,
)


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


def _target(conn, object_name, column_name, source_project="SP_CLO"):
    obj = next(
        o for o in list_target_objects(conn, "SP_CLO")
        if o["object_name"] == object_name and o["source_project"] == source_project
    )
    col = next(
        c for c in list_target_columns(conn, "SP_CLO", obj["object_id"])
        if c["column_name"] == column_name
    )
    return obj["object_id"], col["column_id"]


def _names(sources):
    return [f'{t["object_name"]}.{t["column_name"]}' for t in sources]


def _brute_force_terminals(conn, step_id):
    """Independent oracle built on the UI-04 service: walk down to the leaves."""
    kids = get_upstream_choices(conn, step_id)
    if not kids:
        row = conn.execute(
            """SELECT source_object_id, source_column_id, driving_expression, result_expression
               FROM business_lineage_step WHERE step_id=?""",
            (step_id,),
        ).fetchone()
        base = f"{row[0]}|{row[1]}"
        if row[2] is None and row[3] is None:
            return {base}
        return {f"{base}|{row[2] or ''}|{row[3] or ''}"}
    out = set()
    for k in kids:
        out |= _brute_force_terminals(conn, k["step_id"])
    return out


# --- real DB: whole-database cross-check against the UI-04 service ---------------------

def test_resolver_matches_walk_of_upstream_service_for_every_step(real):
    for obj in list_target_objects(real, "SP_CLO"):
        for col in list_target_columns(real, "SP_CLO", obj["object_id"]):
            resolved = resolve_terminal_sources(real, "SP_CLO", obj["object_id"], col["column_id"])
            for step_id, ids in resolved["branch_terminals"].items():
                assert set(ids) == _brute_force_terminals(real, step_id), step_id


def test_every_step_of_the_database_is_covered_by_some_target(real):
    covered = set()
    for obj in list_target_objects(real, "SP_CLO"):
        for col in list_target_columns(real, "SP_CLO", obj["object_id"]):
            covered |= set(
                resolve_terminal_sources(real, "SP_CLO", obj["object_id"], col["column_id"])["branch_terminals"]
            )
    total = real.execute("SELECT COUNT(*) FROM business_lineage_step").fetchone()[0]
    assert len(covered) == total


def test_initial_target_sources_are_the_union_of_root_choices(real):
    for obj in list_target_objects(real, "SP_CLO"):
        for col in list_target_columns(real, "SP_CLO", obj["object_id"]):
            resolved = resolve_terminal_sources(real, "SP_CLO", obj["object_id"], col["column_id"])
            roots = get_root_choices(real, "SP_CLO", obj["object_id"], col["column_id"])
            union = set()
            for r in roots:
                union |= set(resolved["branch_terminals"][r["step_id"]])
            assert union == {t["terminal_id"] for t in resolved["terminal_sources"]}


def test_resolution_is_deterministic(real):
    first = [resolve_terminal_sources(real, "SP_CLO", o["object_id"], c["column_id"])
             for o in list_target_objects(real, "SP_CLO")
             for c in list_target_columns(real, "SP_CLO", o["object_id"])]
    second = [resolve_terminal_sources(real, "SP_CLO", o["object_id"], c["column_id"])
              for o in list_target_objects(real, "SP_CLO")
              for c in list_target_columns(real, "SP_CLO", o["object_id"])]
    assert first == second


# --- real DB: SP_CLO concrete cases --------------------------------------------------------

def test_sp_clo_fdk_mt_branch_filtering(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    resolved = resolve_terminal_sources(sp_clo, "SP_CLO", obj, col)
    assert _names(sources_for_step(resolved)) == [
        "CM_CLO_OFFER.OFR_HTCS_BOOK_CODE",
        "CM_CLO_OFFER.OFR_HTC_BOOK_CODE",
        "CM_CLO_OFFER.OFR_HTS_BOOK_CODE",
        "CM_CLO_OFFER.e_fdk_mt",
    ]
    roots = get_root_choices(sp_clo, "SP_CLO", obj, col)
    chain = next(r for r in roots if r["upstream_choice_count"] == 1)
    leaf = next(r for r in roots if r["upstream_choice_count"] == 0)
    assert _names(sources_for_step(resolved, leaf["step_id"])) == ["CM_CLO_OFFER.e_fdk_mt"]
    assert len(sources_for_step(resolved, chain["step_id"])) == 3

    level1 = get_upstream_choices(sp_clo, chain["step_id"])[0]
    level2 = get_upstream_choices(sp_clo, level1["step_id"])[0]
    siblings = get_upstream_choices(sp_clo, level2["step_id"])
    assert len(sources_for_step(resolved, level2["step_id"])) == 3
    for sibling in siblings:
        only = sources_for_step(resolved, sibling["step_id"])
        assert _names(only) == [f'{sibling["source_object_name"]}.{sibling["source_column_name"]}']


def test_sp_clo_expression_branches_stay_separate_terminals_with_their_condition(sp_clo):
    obj, col = _target(sp_clo, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    resolved = resolve_terminal_sources(sp_clo, "SP_CLO", obj, col)
    terminals = resolved["terminal_sources"]
    assert [(t["condition"], t["result_expression"]) for t in terminals] == [
        ('AEF_EVENT_CODE=="E011"', '"CLO"'),
        ("ELSE", '"CLO"'),
    ]
    assert len({(t["object_id"], t["column_id"]) for t in terminals}) == 1
    assert all(t["object_type"] == "CONSTANT" and t["leaf_relation_types"] == ["EXPRESSION"] for t in terminals)
    (root,) = get_root_choices(sp_clo, "SP_CLO", obj, col)
    for branch in get_upstream_choices(sp_clo, root["step_id"]):
        (only,) = sources_for_step(resolved, branch["step_id"])
        assert only["condition"] == branch["driving_expression"]


def test_sp_clo_pdt_code_shows_both_offer_branches(sp_clo):
    obj, col = _target(sp_clo, "AR_PAR_LOAN_EVENTS", "PDT_CODE")
    resolved = resolve_terminal_sources(sp_clo, "SP_CLO", obj, col)
    assert [(_names([t])[0], t["condition"]) for t in resolved["terminal_sources"]] == [
        ('"OFFER"."OFFER"', 'AEF_EVENT_CODE=="E011"'),
        ('"OFFER"."OFFER"', "ELSE"),
    ]
    (root,) = get_root_choices(sp_clo, "SP_CLO", obj, col)
    assert len(sources_for_step(resolved, root["step_id"])) == 2


def test_terminals_without_expressions_are_still_merged(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    resolved = resolve_terminal_sources(sp_clo, "SP_CLO", obj, col)
    assert all(t["condition"] is None and t["result_expression"] is None for t in resolved["terminal_sources"])
    assert len(resolved["terminal_sources"]) == 4


def test_sp_clo_contract_id_three_branches(sp_clo):
    obj, col = _target(sp_clo, "PAR_UNPROCESSED_EVENTS", "CONTRACT_ID")
    resolved = resolve_terminal_sources(sp_clo, "SP_CLO", obj, col)
    roots = get_root_choices(sp_clo, "SP_CLO", obj, col)
    assert len(roots) == 3
    sizes = {r["source_column_name"]: len(sources_for_step(resolved, r["step_id"])) for r in roots}
    assert sizes["AEF_EVENT_CODE"] == sizes["AEF_OFFER_ID"] == 1


def test_sp_clo_terminal_kinds_are_reported_as_stored(sp_clo):
    kinds = set()
    for obj in list_target_objects(sp_clo, "SP_CLO"):
        for col in list_target_columns(sp_clo, "SP_CLO", obj["object_id"]):
            for t in resolve_terminal_sources(sp_clo, "SP_CLO", obj["object_id"], col["column_id"])["terminal_sources"]:
                kinds.add(t["object_type"])
    assert kinds == {"DataObject", "CONSTANT", "Synthetic"}


def test_unknown_step_raises(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    with pytest.raises(StepNotFound):
        sources_for_step(resolve_terminal_sources(sp_clo, "SP_CLO", obj, col), "BLS_nope")


def test_unknown_target_resolves_to_nothing(real):
    resolved = resolve_terminal_sources(real, "SP_CLO", "OBJ_missing", "COL_missing")
    assert resolved["terminal_sources"] == [] and resolved["branch_terminals"] == {}


# --- cache ---------------------------------------------------------------------------------------

def test_cache_reuses_result_for_same_target(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    cache = TargetSourceCache()
    first = cache.get(sp_clo, "s1", "SP_CLO", obj, col)
    for _ in range(5):
        assert cache.get(sp_clo, "s1", "SP_CLO", obj, col) is first
    assert cache.compute_count == 1


def test_cache_replaced_when_target_changes(sp_clo):
    a = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    b = _target(sp_clo, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    cache = TargetSourceCache()
    cache.get(sp_clo, "s1", "SP_CLO", *a)
    cache.get(sp_clo, "s1", "SP_CLO", *b)
    assert cache.compute_count == 2
    cache.get(sp_clo, "s1", "SP_CLO", *a)
    assert cache.compute_count == 3


def test_cache_is_scoped_per_session(sp_clo):
    a = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    b = _target(sp_clo, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    cache = TargetSourceCache()
    cache.get(sp_clo, "s1", "SP_CLO", *a)
    cache.get(sp_clo, "s2", "SP_CLO", *b)
    cache.get(sp_clo, "s1", "SP_CLO", *a)
    assert cache.compute_count == 2


def test_cache_invalidated_when_database_changes(sp_clo, db_file):
    a = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    cache = TargetSourceCache()
    cache.get(sp_clo, "s1", "SP_CLO", *a)
    st = os.stat(db_file)
    os.utime(db_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    cache.get(sp_clo, "s1", "SP_CLO", *a)
    assert cache.compute_count == 2


def test_cache_clear(sp_clo):
    a = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    cache = TargetSourceCache()
    cache.get(sp_clo, "s1", "SP_CLO", *a)
    cache.clear("s1")
    cache.get(sp_clo, "s1", "SP_CLO", *a)
    assert cache.compute_count == 2


def test_terminal_flag_hides_descendants_from_target_sources(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    chain = next(r for r in get_root_choices(sp_clo, "SP_CLO", obj, col) if r["upstream_choice_count"] == 1)
    sp_clo.execute("UPDATE business_lineage_step SET is_terminal = 1 WHERE step_id = ?", (chain["step_id"],))
    resolved = resolve_terminal_sources(sp_clo, "SP_CLO", obj, col)
    assert _names(sources_for_step(resolved)) == ["CM_CLO_OFFER.e_fdk_mt"]
    assert set(resolved["branch_terminals"]) == {r["step_id"] for r in get_root_choices(sp_clo, "SP_CLO", obj, col)}
