import shutil
import sqlite3
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "api"))

from lineage_api.catalog import list_target_columns, list_target_objects  # noqa: E402
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


def _names(choices):
    return [f'{c["source_object_name"]}.{c["source_column_name"]}' for c in choices]


# --- real DB: structural guarantees over every step -------------------------------------

def test_every_step_is_reachable_from_a_root_choice(real):
    reached = set()
    stack = [
        c["step_id"]
        for project in ("SP_CLO",)
        for o in list_target_objects(real, project)
        for col in list_target_columns(real, project, o["object_id"])
        for c in get_root_choices(real, project, o["object_id"], col["column_id"])
    ]
    while stack:
        step_id = stack.pop()
        if step_id in reached:
            continue
        reached.add(step_id)
        stack.extend(c["step_id"] for c in get_upstream_choices(real, step_id))
    total = real.execute("SELECT COUNT(*) FROM business_lineage_step").fetchone()[0]
    assert len(reached) == total


def test_choice_counts_match_children_returned(real):
    for step_id, in real.execute("SELECT step_id FROM business_lineage_step").fetchall():
        for choice in get_upstream_choices(real, step_id):
            assert choice["upstream_choice_count"] == len(
                get_upstream_choices(real, choice["step_id"])
            )


def test_children_are_always_one_level_deeper_in_same_path(real):
    rows = real.execute(
        "SELECT step_id, path_id, lineage_level FROM business_lineage_step"
    ).fetchall()
    for r in rows:
        for c in get_upstream_choices(real, r["step_id"]):
            path_id, level = real.execute(
                "SELECT path_id, lineage_level FROM business_lineage_step WHERE step_id=?",
                (c["step_id"],),
            ).fetchone()
            assert path_id == r["path_id"] and level == r["lineage_level"] + 1


def test_unknown_step_raises(real):
    with pytest.raises(StepNotFound):
        get_upstream_choices(real, "BLS_does_not_exist")


# --- real DB: SP_CLO concrete cases --------------------------------------------------------

def test_sp_clo_branching_target_returns_exactly_its_immediate_choices(sp_clo):
    obj, col = _target(sp_clo, "PAR_UNPROCESSED_EVENTS", "CONTRACT_ID")
    choices = get_root_choices(sp_clo, "SP_CLO", obj, col)
    assert _names(choices) == [
        "AR_CLO_ACCOUNTING_EVENTS.AEF_EVENT_CODE",
        "AR_CLO_ACCOUNTING_EVENTS.AEF_OFFER_ID",
        "AR_CLO_ACCOUNTING_EVENTS.e_contract_id",
    ]
    assert [c["upstream_choice_count"] for c in choices] == [0, 0, 1]
    assert [c["has_more_upstream"] for c in choices] == [False, False, True]


def test_sp_clo_selected_branch_hides_sibling_routes(sp_clo):
    obj, col = _target(sp_clo, "PAR_UNPROCESSED_EVENTS", "CONTRACT_ID")
    roots = get_root_choices(sp_clo, "SP_CLO", obj, col)
    terminal = next(c for c in roots if c["source_column_name"] == "AEF_EVENT_CODE")
    branching = next(c for c in roots if c["source_column_name"] == "e_contract_id")
    assert get_upstream_choices(sp_clo, terminal["step_id"]) == []
    children = get_upstream_choices(sp_clo, branching["step_id"])
    assert len(children) == 1
    assert children[0]["target_column_name"] == "e_contract_id"


def test_sp_clo_four_hop_chain_walks_to_three_siblings(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    roots = get_root_choices(sp_clo, "SP_CLO", obj, col)
    # Two distinct steps share the same endpoint; only one continues upstream.
    assert _names(roots) == ["CM_CLO_OFFER.e_fdk_mt"] * 2
    assert len({c["step_id"] for c in roots}) == 2
    assert sorted(c["upstream_choice_count"] for c in roots) == [0, 1]
    level = [next(c for c in roots if c["upstream_choice_count"] == 1)]
    walked = []
    while len(level) == 1:
        walked.append(level[0])
        level = get_upstream_choices(sp_clo, level[0]["step_id"])
    assert [c["relation_type"] for c in walked] == [
        "EXPLICIT_INATTR", "EXPLICIT_PATHFROM_PATHTO", "ENRICHMENT_LOOKUP",
    ]
    assert _names(level) == [
        "CM_CLO_OFFER.OFR_HTCS_BOOK_CODE",
        "CM_CLO_OFFER.OFR_HTC_BOOK_CODE",
        "CM_CLO_OFFER.OFR_HTS_BOOK_CODE",
    ]
    assert all(c["is_terminal"] for c in level)


def test_sp_clo_expression_branches_keep_separate_choices(sp_clo):
    obj, col = _target(sp_clo, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    (root,) = get_root_choices(sp_clo, "SP_CLO", obj, col)
    assert root["upstream_choice_count"] == 2
    branches = get_upstream_choices(sp_clo, root["step_id"])
    assert [(b["relation_type"], b["driving_expression"], b["result_expression"]) for b in branches] == [
        ("EXPRESSION", 'AEF_EVENT_CODE=="E011"', '"CLO"'),
        ("EXPRESSION", "ELSE", '"CLO"'),
    ]


def test_sp_clo_choice_carries_business_process_and_component(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    root = get_root_choices(sp_clo, "SP_CLO", obj, col)[0]
    assert root["business_process_name"] == "CM_CLO_OFFER"
    assert root["component_id"] and root["component_type"]
    assert root["confidence_class"] in {"Explicit", "Inferred"}


# --- is_terminal handling --------------------------------------------------------------------

def test_extractor_populated_is_terminal_is_honoured(sp_clo):
    obj, col = _target(sp_clo, "PAR_UNPROCESSED_EVENTS", "CONTRACT_ID")
    branching = next(
        c for c in get_root_choices(sp_clo, "SP_CLO", obj, col)
        if c["upstream_choice_count"] == 1
    )
    sp_clo.execute(
        "UPDATE business_lineage_step SET is_terminal = 1 WHERE step_id = ?",
        (branching["step_id"],),
    )
    again = next(
        c for c in get_root_choices(sp_clo, "SP_CLO", obj, col)
        if c["step_id"] == branching["step_id"]
    )
    assert again["is_terminal"] is True and again["has_more_upstream"] is False
    assert again["upstream_choice_count"] == 0
    assert get_upstream_choices(sp_clo, branching["step_id"]) == []
