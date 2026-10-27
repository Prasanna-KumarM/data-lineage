# Extractor Requirement: Expression Operands with Precomputed Lineage

## 1. Purpose

When a mapping is produced by an expression, users need to see every operand the expression uses, how each operand is used (condition or value), and where each operand itself comes from. Today the database cannot answer this, so a consumer would have to parse expressions and traverse lineage per request.

The extractor must materialize operands as explicit rows, resolve each to a column, and precompute the upstream lineage of every column operand. This follows the same pattern as `business_process_invocation`: the extractor records the fact, the consumer only reads it.

## 2. What the current database contains (SP_LIQ)

| Finding | Evidence |
|---|---|
| `expression_dependency` holds one row per `EXPRESSION` relation, and that row is always the relation's own source column. | 503 of 503 operand rows have `operand_column_id = column_relation.source_column_id`. |
| An expression with several operands is stored as several relations that share an `expression_id`. | Relations per `expression_id`: 376 have one, 21 have two, 20 have three, 5 have four, 1 has five. |
| Operands that appear only in the condition (`driving_expression`) are not stored. | 307 `EXPRESSION` relations have a real condition. In 208 of them the condition names a column of the source or target object that is not in `expression_dependency` (heuristic name match). |
| Operands have no role. | Already logged as EG-04. |
| Constants appear as columns of a `CONSTANT` object. | 153 of 574 operand rows, with names such as `NullString()` and `"Other error"`. |
| Upstream mappings of an operand column can exist in several Business Processes, because column ids are shared. | Of 574 operand rows, 234 have upstream mappings only in the mapping's own BP, 6 only in other BPs, 16 in both, and 318 have none. |
| `business_lineage_step` is rooted at target columns only, so operand lineage cannot be read from it. | Only 67 of the 185 distinct operand columns appear as a step target. |

The last two rows of findings are why operand lineage must be extracted with explicit Business Process scoping, and cannot be rebuilt reliably from column ids alone.

## 3. Output: table `expression_operand`

One row per operand occurrence in a relation's expression, whether it appears in the condition (`driving_expression`) or in the value (`result_expression`).

| Column | Value |
|---|---|
| `operand_id` | Primary key. Stable deterministic ID: `OPD_` plus a hash of (`relation_id`, `operand_role`, `operand_ordinal`). Must not change across identical re-extractions. |
| `relation_id` | The `column_relation` row that carries the expression. |
| `expression_id` | Same as on the relation. |
| `component_id`, `business_process_id` | The component and Business Process of the relation. This is the scope for resolution and for lineage. |
| `operand_role` | `CONDITION`, `VALUE`, `LOOKUP_KEY` or `UNKNOWN`. Use `UNKNOWN` only when the source does not say. |
| `operand_kind` | `COLUMN`, `CONSTANT`, `LITERAL` or `FUNCTION_CALL`. |
| `operand_ordinal` | Position within its role, counting from 0, in order of appearance in the expression text. |
| `operand_text` | The operand as written, for example `FPR_FIN_PRODUCT` or `NullString()`. |
| `operand_object_id`, `operand_column_id` | The resolved column. Null when the kind is not `COLUMN`, or when resolution failed. |
| `resolution_status` | `RESOLVED`, `UNRESOLVED` or `AMBIGUOUS`. See section 4. |
| `is_relation_source` | 1 when this operand is the relation's own source column, otherwise 0. |
| `lineage_status` | `TRACED`, `TERMINAL`, `NOT_APPLICABLE`, `CYCLE` or `TRUNCATED`. See section 5. |
| `source_count`, `hops_min`, `hops_max` | Summary of the traced lineage. Null unless `lineage_status` is `TRACED`. |
| `evidence_id` | Evidence supporting the operand reference, when available. Do not fabricate evidence. |

`expression_dependency` stays as it is for existing consumers. New consumers read `expression_operand`.

## 4. Resolving operands

- Operand names in a condition or value are resolved in the scope of the component that holds the relation: first the relation's source object, then its target object. A name found in exactly one of them is `RESOLVED`.
- A name found in both with different columns, or in more than one object, is `AMBIGUOUS`. A name found in neither is `UNRESOLVED`. Never pick a candidate.
- For `UNRESOLVED` and `AMBIGUOUS` rows, also write an `extraction_issue` that names the component, the expression text and the operand, and leave `operand_column_id` null.
- Operands inside string literals are not operands. `FPR_FIN_PRODUCT == "RIPI"` has one operand.
- Constants and literals get a row with the matching `operand_kind`, and `lineage_status = NOT_APPLICABLE`.

## 5. Output: table `operand_lineage_step`

For every operand with `operand_kind = COLUMN` and `resolution_status = RESOLVED`, the extractor materializes the upstream lineage with the same traversal rules and the same columns as `business_lineage_step`, with these differences:

- The root is the operand, not a target column: add `operand_id` (foreign key to `expression_operand`) and drop the `root_target_*` columns.
- Add `parent_step_id` so that paths can be followed without matching on endpoint and level.
- Every step carries `business_process_id`, and traversal stays inside the operand's Business Process. It crosses to another Business Process only through a `RESOLVED` row in `business_process_invocation`.

`lineage_status` on `expression_operand` is set as follows:

- `TRACED`: at least one upstream step exists, and traversal reached its end.
- `TERMINAL`: the operand column has no upstream mapping in scope. It is already an ultimate source.
- `CYCLE`: traversal met a cycle. Steps up to the cycle are kept and an `extraction_issue` is written.
- `TRUNCATED`: a depth limit was reached. The limit must be documented, and an `extraction_issue` is written.

A separate table is preferred over adding an operand root to `business_lineage_step`, so that existing queries on `business_lineage_step` are not affected.

## 6. Examples

All examples are from SP_LIQ.

### 6.1 Condition operand that is missing today

Relation `MAP_e9ec4a68d0c04e1bd4e27ab10afe9d18fcc2af36e9562c96127bc4a6c29b7334`: target `PAR_GFRS_LIQ_TRADES.CTR_ID`.

- Condition: `FPR_FIN_PRODUCT == "RIPI"`
- Value: `"FAC"+FAC_ID`
- Today: one operand row, `FAC_ID`.

Expected `expression_operand` rows:

| Role | Ordinal | Text | Kind | Resolved to | Lineage |
|---|---|---|---|---|---|
| `CONDITION` | 0 | `FPR_FIN_PRODUCT` | `COLUMN` | `FPR_FIN_PRODUCT` in the relation's source object | `TRACED` or `TERMINAL` |
| `VALUE` | 0 | `FAC_ID` | `COLUMN` | `FAC_ID` (this is the relation's source column, `is_relation_source = 1`) | `TRACED`, with steps in `operand_lineage_step` |

A trace of `FAC_ID` by column id alone, without Business Process scoping, reaches 19 upstream columns and 7 terminal columns. The scoped figures will be the extractor's output and must not be larger.

### 6.2 Operand on the target side, constant value

Condition `e_fee_id == "x"`, value `NullString()`, target `PAR_GFRS_LIQ_TRADES.e_fee_id`.

| Role | Text | Kind | Resolved to | Lineage |
|---|---|---|---|---|
| `CONDITION` | `e_fee_id` | `COLUMN` | `e_fee_id` in the relation's target object | `TRACED` or `TERMINAL` |
| `VALUE` | `NullString()` | `CONSTANT` | none | `NOT_APPLICABLE` |

### 6.3 Several operands in one condition

Condition `CTR_TYPE == "ACCRUE_FEE" and e_afe_id<>"x"`, value `ACC_AMT_YTD - ACC_AMT_PAY`.

Expected: two `CONDITION` rows (`CTR_TYPE`, `e_afe_id`) and two `VALUE` rows (`ACC_AMT_YTD`, `ACC_AMT_PAY`). Today only the value operand carried by each relation is stored.

## 7. Idempotence and integrity

- Re-extracting unchanged input produces the same `operand_id` values and the same rows.
- `(relation_id, operand_role, operand_ordinal)` is unique.
- `relation_id`, `component_id` and `business_process_id` must reference existing rows, and the component's Business Process must equal `business_process_id`.
- When `resolution_status` is `RESOLVED` and the kind is `COLUMN`, the column must exist in the referenced object. Otherwise `operand_column_id` is null.
- When `lineage_status` is `TRACED`, `operand_lineage_step` has at least one row for the operand, and `source_count`, `hops_min` and `hops_max` agree with those rows.
- Every `EXPRESSION` relation has at least one `VALUE` operand row, unless its expression is a constant with no operands, in which case it has a `CONSTANT` row.
- Rebuild both tables in the same transaction as the rest of the extraction. No stale rows may remain.

Suggested indexes:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_operand_slot
    ON expression_operand(relation_id, operand_role, operand_ordinal);
CREATE INDEX IF NOT EXISTS idx_operand_relation ON expression_operand(relation_id);
CREATE INDEX IF NOT EXISTS idx_operand_step_root ON operand_lineage_step(operand_id, lineage_level);
CREATE INDEX IF NOT EXISTS idx_operand_step_parent ON operand_lineage_step(parent_step_id);
```

## 8. Consumer contract

- The API reads `expression_operand` by `relation_id` and groups the rows by `operand_role`. It does not parse expressions.
- Operand lineage is read from `operand_lineage_step` by `operand_id`. The API does not traverse `column_relation` at request time.
- Older databases without the new tables keep today's behaviour: operands come from `expression_dependency`, ungrouped, with no operand lineage.
- The UI shows operands under Condition and Value, with a lineage status badge and source count on each, and lets the user expand an operand into its lineage.

## 9. Acceptance checks

For SP_LIQ:

- Every `EXPRESSION` relation has at least one operand row, and the 503 current value operands are all present as `VALUE` rows with `is_relation_source = 1`.
- For the 307 relations with a real condition, every column named in the condition has a `CONDITION` row. A name that cannot be resolved has an `UNRESOLVED` row and an `extraction_issue`.
- Example 6.1 produces the two rows shown, and `FAC_ID` has steps in `operand_lineage_step` that stay inside the relation's Business Process.
- No `operand_lineage_step` row has a different `business_process_id` from its operand, unless the step is reached through a `RESOLVED` invocation.
- Re-running extraction produces identical `operand_id` values and no duplicate rows.
- A fixture with an operand name that exists in both the source and target objects is `AMBIGUOUS`. A fixture with a cycle is `CYCLE` and leaves an `extraction_issue`.

## 10. Current repository boundary

This repository holds the generated databases and the read-only API, not the extractor. Once the tables are populated, the API can add the operand endpoints with a fallback for databases that lack the tables, and the UI can group and expand operands without any traversal of its own.
