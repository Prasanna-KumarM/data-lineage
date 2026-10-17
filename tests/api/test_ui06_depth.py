import shutil
import sqlite3
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.catalog import list_target_columns, list_target_objects  # noqa: E402
from lineage_api.depth import get_remaining_depth  # noqa: E402
from lineage_api.migrations import add_business_process_columns  # noqa: E402
from lineage_api.upstream import (  # noqa: E402
    StepNotFound,
    get_root_choices,
    get_upstream_choices,
)


@pytest.fixture()
def real(lineage_db_path, tmp_path):
    target = tmp_path / "lineage.db"
    shutil.copy(lineage_db_path, target)
    c = sqlite3.connect(target)
    c.row_factory = sqlite3.Row
    add_business_process_columns(c)
    yield c
    c.close()


@pytest.fixture()
def sp_clo(real, lineage_db_path):
    if lineage_db_path.parent.name != "SP_CLO":
        pytest.skip("SP_CLO-specific expectations")
    return real


def _target(conn, object_name, column_name):
    obj = next(
        o for o in list_target_objects(conn, "SP_CLO")
        if o["object_name"] == object_name and o["source_project"] == "SP_CLO"
    )
    col = next(
        c for c in list_target_columns(conn, "SP_CLO", obj["object_id"])
        if c["column_name"] == column_name
    )
    return obj["object_id"], col["column_id"]


def _leaf_depths(conn, step_id):
    """Oracle: depths of every terminal route, walked with the UI-04 service."""
    kids = get_upstream_choices(conn, step_id)
    if not kids:
        return {0}
    return {1 + d for k in kids for d in _leaf_depths(conn, k["step_id"])}


# --- real DB: whole-database cross-check -----------------------------------------------------

def test_depth_matches_route_walk_for_every_step(real):
    steps = [r[0] for r in real.execute("SELECT step_id FROM business_lineage_step")]
    for step_id in steps:
        depths = _leaf_depths(real, step_id)
        result = get_remaining_depth(real, step_id)
        assert result["remaining_hops_min"] == min(depths), step_id
        assert result["remaining_hops_max"] == max(depths), step_id
        assert result["is_terminal"] == (max(depths) == 0)
        assert (result["remaining_hops_exact"] is not None) == (min(depths) == max(depths))


def test_depth_decreases_by_one_per_hop_along_every_branch(real):
    for step_id, in real.execute("SELECT step_id FROM business_lineage_step").fetchall():
        here = get_remaining_depth(real, step_id)
        for kid in get_upstream_choices(real, step_id):
            below = get_remaining_depth(real, kid["step_id"])
            assert below["remaining_hops_max"] <= here["remaining_hops_max"] - 1
            assert below["remaining_hops_min"] >= here["remaining_hops_min"] - 1


# --- real DB: SP_CLO concrete cases ------------------------------------------------------------

def test_sp_clo_four_hop_chain_counts_down_to_terminal(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    roots = get_root_choices(sp_clo, "SP_CLO", obj, col)
    # Both mappings reach e_fdk_mt, so both have the same three hops left.
    for root in roots:
        assert get_remaining_depth(sp_clo, root["step_id"])["remaining_hops_exact"] == 3
    chain = roots[0]

    expected = [3, 2, 1]
    step = chain
    for remaining in expected:
        result = get_remaining_depth(sp_clo, step["step_id"])
        assert result["remaining_hops_exact"] == remaining
        assert result["is_terminal"] is False
        step = get_upstream_choices(sp_clo, step["step_id"])[0]
    assert get_remaining_depth(sp_clo, step["step_id"])["remaining_hops_exact"] == 0


def test_sp_clo_expression_root_has_one_remaining_hop(sp_clo):
    obj, col = _target(sp_clo, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    (root,) = get_root_choices(sp_clo, "SP_CLO", obj, col)
    assert get_remaining_depth(sp_clo, root["step_id"])["remaining_hops_exact"] == 1
    for branch in get_upstream_choices(sp_clo, root["step_id"]):
        assert get_remaining_depth(sp_clo, branch["step_id"])["is_terminal"] is True


def test_unknown_step_raises(real):
    with pytest.raises(StepNotFound):
        get_remaining_depth(real, "BLS_nope")


# --- real DB copy with one deeper route grafted onto a real branch ---------------------------

def _graft_longer_route(conn):
    """Give one BOOK_CODE sibling an extra upstream hop so routes differ in length."""
    obj, col = _target(conn, "CM_PAR_LOAN_TRADES", "FDK_MT")
    chain = next(r for r in get_root_choices(conn, "SP_CLO", obj, col) if r["upstream_choice_count"] == 1)
    step = chain
    while True:
        kids = get_upstream_choices(conn, step["step_id"])
        if len(kids) != 1:
            break
        step = kids[0]
    # `step` is the last single-child step (level 2); its children are the siblings.
    siblings = get_upstream_choices(conn, step["step_id"])
    victim = siblings[0]
    row = dict(conn.execute(
        "SELECT * FROM business_lineage_step WHERE step_id = ?", (victim["step_id"],)
    ).fetchone())
    row.update(
        step_id="BLS_grafted", lineage_level=row["lineage_level"] + 1,
        hop_count=row["hop_count"] + 1,
        target_object_id=row["source_object_id"], target_column_id=row["source_column_id"],
        target_object_name=row["source_object_name"], target_column_name=row["source_column_name"],
        is_terminal=0,
    )
    cols = ", ".join(row)
    conn.execute(
        f"INSERT INTO business_lineage_step ({cols}) VALUES ({', '.join('?' * len(row))})",
        list(row.values()),
    )
    return chain, step, victim, siblings


def test_variable_depth_reports_min_max_and_hides_exact(sp_clo):
    chain, level2, victim, siblings = _graft_longer_route(sp_clo)
    top = get_remaining_depth(sp_clo, chain["step_id"])
    assert (top["remaining_hops_min"], top["remaining_hops_max"]) == (3, 4)
    assert top["remaining_hops_exact"] is None and top["is_terminal"] is False
    at2 = get_remaining_depth(sp_clo, level2["step_id"])
    assert (at2["remaining_hops_min"], at2["remaining_hops_max"]) == (1, 2)
    assert get_remaining_depth(sp_clo, victim["step_id"])["remaining_hops_exact"] == 1
    other = next(s for s in siblings if s["step_id"] != victim["step_id"])
    assert get_remaining_depth(sp_clo, other["step_id"])["remaining_hops_exact"] == 0


def test_depth_is_computed_only_for_the_selected_branch(sp_clo):
    chain, level2, victim, siblings = _graft_longer_route(sp_clo)
    other = next(s for s in siblings if s["step_id"] != victim["step_id"])
    # The longer sibling route must not leak into a sibling's own depth.
    assert get_remaining_depth(sp_clo, other["step_id"])["remaining_hops_max"] == 0


def test_is_terminal_flag_stops_the_walk(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    chain = next(r for r in get_root_choices(sp_clo, "SP_CLO", obj, col) if r["upstream_choice_count"] == 1)
    sp_clo.execute("UPDATE business_lineage_step SET is_terminal = 1 WHERE step_id = ?", (chain["step_id"],))
    assert get_remaining_depth(sp_clo, chain["step_id"])["is_terminal"] is True


def test_repeating_endpoints_terminate(sp_clo):
    """Endpoints that repeat across levels (A->B->A) cannot loop: levels only increase."""
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    chain = next(r for r in get_root_choices(sp_clo, "SP_CLO", obj, col) if r["upstream_choice_count"] == 1)
    row = dict(sp_clo.execute("SELECT * FROM business_lineage_step WHERE step_id = ?", (chain["step_id"],)).fetchone())
    row.update(
        step_id="BLS_cycle", lineage_level=row["lineage_level"] + 4,
        source_object_id=row["target_object_id"], source_column_id=row["target_column_id"],
        target_object_id=row["source_object_id"], target_column_id=row["source_column_id"],
    )
    sp_clo.execute(
        f"INSERT INTO business_lineage_step ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
        list(row.values()),
    )
    result = get_remaining_depth(sp_clo, chain["step_id"])
    assert result["remaining_hops_max"] >= 3
