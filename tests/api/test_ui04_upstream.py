import shutil
import sqlite3
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "src" / "api"))

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


def test_children_are_one_level_deeper_with_matching_endpoint_root_and_process(real):
    for r in real.execute("SELECT * FROM business_lineage_step").fetchall():
        for c in get_upstream_choices(real, r["step_id"]):
            child = real.execute("SELECT * FROM business_lineage_step WHERE step_id=?", (c["step_id"],)).fetchone()
            assert child["lineage_level"] == r["lineage_level"] + 1
            assert (child["root_target_object_id"], child["root_target_column_id"]) == (
                r["root_target_object_id"], r["root_target_column_id"])
            assert child["business_process_id"] == r["business_process_id"]
            assert (child["target_object_id"], child["target_column_id"]) == (
                r["source_object_id"], r["source_column_id"])


def test_steps_reaching_the_same_endpoint_have_identical_upstream(real):
    """Two mappings into one source column share that column's upstream, whatever their path_id."""
    groups = {}
    for r in real.execute("SELECT * FROM business_lineage_step").fetchall():
        key = (r["root_target_object_id"], r["root_target_column_id"], r["business_process_id"],
               r["lineage_level"], r["source_object_id"], r["source_column_id"])
        groups.setdefault(key, []).append(r["step_id"])
    shared = [steps for steps in groups.values() if len(steps) > 1]
    assert shared
    for steps in shared:
        children = [sorted(c["step_id"] for c in get_upstream_choices(real, s)) for s in steps]
        assert all(c == children[0] for c in children), steps


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
    # Two mappings (one per component) reach the same endpoint, merged into one card.
    assert _names(roots) == ["CM_CLO_OFFER.e_fdk_mt"]
    assert roots[0]["contributor_count"] == 2
    assert [c["upstream_choice_count"] for c in roots] == [1]
    level = roots
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


def test_sp_clo_contract_id_both_mappings_lead_to_the_same_three_steps(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "CONTRACT_ID")
    roots = get_root_choices(sp_clo, "SP_CLO", obj, col)
    # The two mappings merge into one card; its contributors carry both components.
    assert _names(roots) == ["CM_CLO_OFFER.e_contract_id"]
    assert roots[0]["contributor_count"] == 2
    assert [c["upstream_choice_count"] for c in roots] == [1]
    below = get_upstream_choices(sp_clo, roots[0]["step_id"])
    assert _names(below) == ["CM_CLO_OFFER.OFR_ID"]
    # The three rule calls merge into one step with three contributors.
    assert below[0]["contributor_count"] == 3


def test_sp_clo_counterparty_country_both_mappings_lead_to_the_same_lookup(sp_clo):
    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "COUNTERPARTY_COUNTRY_ISO_CODE")
    roots = get_root_choices(sp_clo, "SP_CLO", obj, col)
    assert [c["upstream_choice_count"] for c in roots] == [1]
    assert roots[0]["contributor_count"] == 2
    below = get_upstream_choices(sp_clo, roots[0]["step_id"])
    assert below[0]["component_name"] == "CLO_CM_OFR_Enrichment"


def test_sp_clo_every_same_endpoint_root_pair_now_agrees(sp_clo):
    for o in list_target_objects(sp_clo, "SP_CLO"):
        for c in list_target_columns(sp_clo, "SP_CLO", o["object_id"]):
            roots = get_root_choices(sp_clo, "SP_CLO", o["object_id"], c["column_id"])
            by_endpoint = {}
            for r in roots:
                by_endpoint.setdefault((r["source_object_id"], r["source_column_id"]), set()).add(r["upstream_choice_count"])
            assert all(len(counts) == 1 for counts in by_endpoint.values()), (o["object_name"], c["column_name"])


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


def test_merged_step_detail_lists_its_contributors(sp_clo):
    from lineage_api.detail import get_step_detail

    obj, col = _target(sp_clo, "CM_PAR_LOAN_TRADES", "FDK_MT")
    (root,) = get_root_choices(sp_clo, "SP_CLO", obj, col)
    assert root["contributor_components"] == ["CM_CLO_OFR_COMM Mapping", "CM_CLO_OFR_Fair Value Mapping"]
    detail = get_step_detail(sp_clo, root["step_id"])
    assert [(c["component_name"], c["relation_type"]) for c in detail["contributors"]] == [
        ("CM_CLO_OFR_COMM Mapping", "EXPLICIT_INATTR"),
        ("CM_CLO_OFR_Fair Value Mapping", "EXPLICIT_INATTR"),
    ]
    assert len({c["relation_id"] for c in detail["contributors"]}) == 2


def test_single_mapping_steps_have_one_contributor(sp_clo):
    from lineage_api.detail import get_step_detail

    obj, col = _target(sp_clo, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    (root,) = get_root_choices(sp_clo, "SP_CLO", obj, col)
    assert root["contributor_count"] == 1
    detail = get_step_detail(sp_clo, root["step_id"])
    assert len(detail["contributors"]) == 1
