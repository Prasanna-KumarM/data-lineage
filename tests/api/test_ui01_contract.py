"""UI-01: fields and invariants of the generated lineage DB that the API depends on."""
import pytest

REQUIRED_COLUMNS = {
    "business_lineage_step": {
        "step_id", "path_id", "lineage_level", "is_terminal",
        "root_target_object_id", "root_target_column_id",
        "root_target_object_name", "root_target_column_name",
        "relation_id", "relation_type",
        "source_object_id", "source_column_id", "source_object_name", "source_column_name",
        "target_object_id", "target_column_id", "target_object_name", "target_column_name",
        "component_id", "component_name", "component_type",
        "confidence_class", "confidence_reason_code",
        "traversal_path", "driving_expression", "result_expression", "expression_id",
        "hop_count",
    },
    "column_relation": {
        "relation_id", "relation_type", "component_id", "expression_id",
        "source_object_id", "source_column_id", "target_object_id", "target_column_id",
        "traversal_path", "driving_expression", "result_expression",
    },
    "canonical_object": {"object_id", "object_name", "object_type", "source_project"},
    "canonical_column": {"column_id", "object_id", "column_name"},
    "component": {"component_id", "business_process_id", "component_name", "component_type"},
    "business_process": {"business_process_id", "business_process_name", "project_name"},
    "canonical_confidence": {
        "relation_id", "confidence_class", "confidence_reason_code", "confidence_reason",
    },
    "expression_dependency": {"expression_id", "relation_id", "operand_object_id", "operand_column_id"},
    "lineage_gap": {"lineage_gap_id", "business_process_id", "gap_reason_code", "explanation"},
}


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


@pytest.mark.parametrize("table", sorted(REQUIRED_COLUMNS))
def test_required_columns_present(conn, table):
    missing = REQUIRED_COLUMNS[table] - _columns(conn, table)
    assert not missing, f"{table} is missing columns: {sorted(missing)}"


def test_integrity_and_foreign_keys(conn):
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_step_ids_unique(conn):
    rows, distinct = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT step_id) FROM business_lineage_step"
    ).fetchone()
    assert rows == distinct


def test_every_path_has_exactly_one_level_zero_step(conn):
    bad = conn.execute(
        """SELECT path_id FROM business_lineage_step GROUP BY path_id
           HAVING SUM(lineage_level = 0) != 1"""
    ).fetchall()
    assert bad == []


def test_every_deeper_step_has_a_parent_level(conn):
    orphans = conn.execute(
        """SELECT COUNT(*) FROM business_lineage_step b WHERE lineage_level > 0
           AND NOT EXISTS (SELECT 1 FROM business_lineage_step p
                           WHERE p.path_id = b.path_id AND p.lineage_level = b.lineage_level - 1)"""
    ).fetchone()[0]
    assert orphans == 0


def test_hop_count_is_level_plus_one(conn):
    bad = conn.execute(
        "SELECT COUNT(*) FROM business_lineage_step WHERE hop_count != lineage_level + 1"
    ).fetchone()[0]
    assert bad == 0


def test_steps_reference_existing_relations_and_components(conn):
    assert conn.execute(
        """SELECT COUNT(*) FROM business_lineage_step s
           LEFT JOIN column_relation r ON r.relation_id = s.relation_id
           WHERE r.relation_id IS NULL"""
    ).fetchone()[0] == 0
    assert conn.execute(
        """SELECT COUNT(*) FROM business_lineage_step s
           LEFT JOIN component c ON c.component_id = s.component_id
           WHERE s.component_id IS NOT NULL AND c.component_id IS NULL"""
    ).fetchone()[0] == 0


def test_expression_fields_populated_together(conn):
    bad = conn.execute(
        """SELECT COUNT(*) FROM business_lineage_step
           WHERE (expression_id IS NULL) != (driving_expression IS NULL)
              OR (expression_id IS NULL) != (result_expression IS NULL)"""
    ).fetchone()[0]
    assert bad == 0


def test_step_listing_is_repeatable(conn):
    sql = "SELECT step_id FROM business_lineage_step ORDER BY step_id"
    assert conn.execute(sql).fetchall() == conn.execute(sql).fetchall()
