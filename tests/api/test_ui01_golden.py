"""UI-01: golden regression snapshots of business_lineage_step for known targets."""

GOLDEN = {
    ("SP_CLO", "AR_PAR_LOAN_EVENTS", "MDE_CODE"): [
        # (step_id, level, relation_type, source, target, driving_expression, result_expression)
        (
            "BLS_7d6bf1bf4b285d521bb89b0318cc74951a4b431cfd6519f9fbba7f3026699f52", 0,
            "EXPLICIT_PATHFROM_PATHTO",
            "AR_CLO_ACCOUNTING_EVENTS.e_product_group", "AR_PAR_LOAN_EVENTS.MDE_CODE",
            None, None,
        ),
        (
            "BLS_c46d912716a61f8fc16670de4c170fcaada3f64486b35b617f456d7af4254bec", 1,
            "EXPRESSION",
            '"CLO"."CLO"', "AR_CLO_ACCOUNTING_EVENTS.e_product_group",
            'AEF_EVENT_CODE=="E011"', '"CLO"',
        ),
        (
            "BLS_feab5fb599768bcb0bf06e3f0be25d684f8239553eee5df86456a74d80a244fa", 1,
            "EXPRESSION",
            '"CLO"."CLO"', "AR_CLO_ACCOUNTING_EVENTS.e_product_group",
            "ELSE", '"CLO"',
        ),
    ],
}


def _steps(conn, table, column):
    rows = conn.execute(
        """SELECT step_id, lineage_level, relation_type,
                  source_object_name || '.' || source_column_name,
                  target_object_name || '.' || target_column_name,
                  driving_expression, result_expression
           FROM business_lineage_step
           WHERE root_target_object_name = ? AND root_target_column_name = ?
           ORDER BY lineage_level, step_id""",
        (table, column),
    ).fetchall()
    return [tuple(r) for r in rows]


def test_golden_targets_match_snapshot(conn, lineage_db_path):
    for (project, table, column), expected in GOLDEN.items():
        if lineage_db_path.parent.name != project:
            continue
        assert _steps(conn, table, column) == expected, f"{project}/{table}.{column}"


def test_same_endpoint_expression_branches_stay_distinct(conn):
    steps = _steps(conn, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    level1 = [s for s in steps if s[1] == 1]
    assert len(level1) == 2
    assert len({(s[3], s[4]) for s in level1}) == 1
    assert len({s[5] for s in level1}) == 2
