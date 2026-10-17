import shutil
import sqlite3
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "src" / "api"))

from lineage_api.catalog import list_target_columns, list_target_objects  # noqa: E402
from lineage_api.detail import (  # noqa: E402
    RelationNotFound,
    get_relation_detail,
    get_step_detail,
)
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


def _steps_of_type(conn, relation_type):
    return [r[0] for r in conn.execute(
        "SELECT step_id FROM business_lineage_step WHERE relation_type = ? ORDER BY step_id",
        (relation_type,),
    )]


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


# --- real DB: every step agrees with the materialised step row ---------------------------------

def test_step_detail_matches_step_row_for_every_step(real):
    for s in real.execute("SELECT * FROM business_lineage_step").fetchall():
        d = get_step_detail(real, s["step_id"])
        assert d["relation_id"] == s["relation_id"]
        assert d["relation_type"] == s["relation_type"]
        assert (d["source"]["object_id"], d["source"]["column_id"]) == (s["source_object_id"], s["source_column_id"])
        assert (d["target"]["object_id"], d["target"]["column_id"]) == (s["target_object_id"], s["target_column_id"])
        assert (d["source"]["object_name"], d["source"]["column_name"]) == (s["source_object_name"], s["source_column_name"])
        assert (d["target"]["object_name"], d["target"]["column_name"]) == (s["target_object_name"], s["target_column_name"])
        assert d["component"]["component_id"] == s["component_id"]
        assert d["component"]["component_name"] == s["component_name"]
        assert d["component"]["component_type"] == s["component_type"]
        assert d["confidence"]["confidence_class"] == s["confidence_class"]
        assert d["confidence"]["reason_code"] == s["confidence_reason_code"]
        assert d["traversal_path"] == s["traversal_path"]
        assert d["driving_expression"] == s["driving_expression"]
        assert d["result_expression"] == s["result_expression"]
        assert d["expression_id"] == s["expression_id"]
        assert d["business_process"] == {
            "business_process_id": s["business_process_id"],
            "business_process_name": s["business_process_name"],
        }
        assert (d["step_id"], d["path_id"], d["lineage_level"]) == (s["step_id"], s["path_id"], s["lineage_level"])


def test_dependencies_match_table_for_every_relation(real):
    for (rid,) in real.execute("SELECT DISTINCT relation_id FROM business_lineage_step").fetchall():
        expected = real.execute(
            "SELECT COUNT(*) FROM expression_dependency WHERE relation_id = ?", (rid,)
        ).fetchone()[0]
        deps = get_relation_detail(real, rid)["dependencies"]
        assert len(deps) == expected
        assert [d["operand_order"] for d in deps] == sorted(d["operand_order"] for d in deps)


def test_relation_lists_every_step_that_uses_it(real):
    shared = real.execute(
        "SELECT relation_id FROM business_lineage_step GROUP BY relation_id HAVING COUNT(*) > 1"
    ).fetchall()
    assert shared
    for (rid,) in shared:
        expected = [r[0] for r in real.execute(
            "SELECT step_id FROM business_lineage_step WHERE relation_id = ? ORDER BY step_id", (rid,))]
        assert get_relation_detail(real, rid)["step_ids"] == expected
        assert len(expected) > 1


def test_detail_is_json_serialisable(real):
    import json
    for (sid,) in real.execute("SELECT step_id FROM business_lineage_step").fetchall():
        json.dumps(get_step_detail(real, sid))


def test_unknown_ids_raise(real):
    with pytest.raises(StepNotFound):
        get_step_detail(real, "BLS_nope")
    with pytest.raises(RelationNotFound):
        get_relation_detail(real, "MAP_nope")


# --- real DB: relation kinds -------------------------------------------------------------------------

def test_not_persisted_exposes_stored_reason_only(real):
    steps = _steps_of_type(real, "NOT_PERSISTED")
    assert len(steps) == 6
    for sid in steps:
        d = get_step_detail(real, sid)
        assert d["persistence"] == {
            "status": "NOT_PERSISTED",
            "reason_code": "TARGET_ATTRIBUTE_ABSENT_FROM_EDF_MAPPING",
            "reason": None,
        }
        assert d["source"]["object_name"] == "NOT_PERSISTED"
        assert d["confidence"]["confidence_class"] == "Inferred"


def test_persisted_relations_have_no_persistence_block(real):
    for rt in ("EXPLICIT_INATTR", "AUTO_MAP_BY_NAME", "EXPRESSION"):
        assert get_step_detail(real, _steps_of_type(real, rt)[0])["persistence"] is None


def test_expression_steps_separate_condition_from_value(real):
    for sid in _steps_of_type(real, "EXPRESSION"):
        d = get_step_detail(real, sid)
        assert d["expression_id"]
        assert d["driving_expression"] and d["result_expression"]
        assert d["driving_expression"] != d["result_expression"]
        assert len(d["dependencies"]) >= 1


def test_constant_and_function_relations_have_no_expression_block(real):
    for rt in ("CONSTANT_ASSIGNMENT", "RUNTIME_FUNCTION_ASSIGNMENT"):
        for sid in _steps_of_type(real, rt):
            d = get_step_detail(real, sid)
            assert d["expression_id"] is None
            assert d["driving_expression"] is None and d["result_expression"] is None
            assert d["relation_type"] == rt


def test_enrichment_steps_carry_traversal_and_component(real):
    for sid in _steps_of_type(real, "ENRICHMENT_LOOKUP"):
        d = get_step_detail(real, sid)
        assert d["component"]["component_name"]
        assert d["relation_type"] == "ENRICHMENT_LOOKUP"


# --- real DB: SP_CLO concrete case ---------------------------------------------------------------------------

def test_sp_clo_mde_code_case_branches(sp_clo):
    obj, col = _target(sp_clo, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    (root,) = get_root_choices(sp_clo, "SP_CLO", obj, col)
    top = get_step_detail(sp_clo, root["step_id"])
    assert top["relation_type"] == "EXPLICIT_PATHFROM_PATHTO"
    assert top["business_process"]["business_process_name"] == "AR_CLO_EVENT_PROCESSING"
    assert top["source"]["column_name"] == "e_product_group"
    assert top["target"]["column_name"] == "MDE_CODE"
    assert top["persistence"] is None and top["dependencies"] == []

    branches = {
        b["driving_expression"]: get_step_detail(sp_clo, b["step_id"])
        for b in get_upstream_choices(sp_clo, root["step_id"])
    }
    assert set(branches) == {'AEF_EVENT_CODE=="E011"', "ELSE"}
    assert all(b["result_expression"] == '"CLO"' for b in branches.values())
    assert len({b["relation_id"] for b in branches.values()}) == 2
    assert len({b["expression_id"] for b in branches.values()}) == 2
