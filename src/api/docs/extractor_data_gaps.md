# Extractor data gaps register

Gaps found in the generated `lineage.db` while building the lineage UI. Each entry says what is
missing or inconsistent in the stored data, what it costs the UI today, and what the extractor
could change. The UI never rewrites lineage to compensate; workarounds are noted where they exist.

Data examined: `outputs/SP_CLO/lineage.db` (schema_version 1.0.0, parser_version 1.0.0).

**Status values:** Open, Workaround in API, Unverified, Fixed (extractor).

## Summary

| ID | Gap | Status | Found in |
|---|---|---|---|
| EG-01 | `business_lineage_step.is_terminal` never populated | Open | Analysis |
| EG-02 | Business Process fields missing from `business_lineage_step` | Workaround in API | UI-02 |
| EG-03 | `canonical_confidence.confidence_reason` text is empty | Open | UI-07 |
| EG-04 | `expression_dependency` has no operand role | Open | UI-07 |
| EG-05 | `AptitudeServiceTarget` components are not linked to objects | Open | UI-03 |
| EG-06 | `lineage_gap` has no rows, so gap handling is unverified | Unverified | UI-07 |
| EG-07 | `extraction_run` has no source file name or hash | Open | UI-05 |
| EG-08 | Constants and functions are represented inconsistently | Open | UI-05 |
| EG-09 | No explicit parent link between steps | Open | UI-04 |
| EG-10 | `hop_count` is the step depth, not the path length | Open | Analysis |
| EG-11 | Same object name exists for several `source_project` values | Open | UI-03 |

## Entries

### EG-01 — `is_terminal` never populated

- **Gap details:** `business_lineage_step.is_terminal` is 0 on all 320 rows, although 257 of them have no upstream step.
- **Impact:** a terminal step cannot be read from the data. The API derives it from the absence of child steps.
- **Suggested resolution:** set `is_terminal = 1` when the step's source endpoint has no further upstream relation.
- **Improvement expected in the UI:** none required. The API already uses the flag when it is set (UI-04, UI-05, UI-06). Populating it lets the UI trust the stored value and lets the API check it against the derived one.

### EG-02 — Business Process fields missing from `business_lineage_step`

- **Gap details:** the table has no `business_process_id` or `business_process_name`. They are reachable only through `component` and `business_process`.
- **Impact:** every API query joins two extra tables to get the Business Process.
- **Suggested resolution:** add both columns to the model, materializer, DDL and insert, as specified in UI-02. `column_relation` stays authoritative.
- **Improvement expected in the UI:** simpler and faster queries. The API migration `src/api/lineage_api/migrations.py` adds and fills the columns until the extractor does, and can then be removed.

### EG-03 — Confidence reason text is empty

- **Gap details:** `canonical_confidence.confidence_reason` is empty on all rows. Only `confidence_reason_code` is set, for example `TARGET_ATTRIBUTE_ABSENT_FROM_EDF_MAPPING` on the 6 `NOT_PERSISTED` steps.
- **Impact:** the detail drawer can only show a code. The API returns `reason: null` and does not invent text.
- **Suggested resolution:** populate `confidence_reason` with a plain-language sentence for each reason code, or publish a code-to-text list.
- **Improvement expected in the UI:** the detail drawer shows a readable explanation for inferred and not-persisted steps instead of a code.

### EG-04 — Expression dependencies have no operand role

- **Gap details:** `expression_dependency` holds `operand_order`, object and column, but nothing saying whether an operand belongs to the condition or to the value of the expression.
- **Impact:** the drawer can list operands but cannot say how each one is used. Operands that are constants appear as objects named like `"CLO"`.
- **Suggested resolution:** add an operand role column (condition, value, lookup key, or similar).
- **Improvement expected in the UI:** operands grouped under Condition and Value in the detail drawer.

### EG-05 — Target components are not linked to objects

- **Gap details:** `component_port.object_id` is empty and `direction` is `UNKNOWN` for all 7 `AptitudeServiceTarget` components. Two of them are `... Errors` targets.
- **Impact:** the approved target population cannot be read from the data. The UI takes it from the root objects of `business_lineage_step`, which matches the 5 non-error targets.
- **Suggested resolution:** set `object_id` and `direction` on target component ports, or add a flag on `canonical_object` marking target objects.
- **Improvement expected in the UI:** the Target Object list comes from an explicit target marker, and error targets can be left out or shown on purpose.

### EG-06 — `lineage_gap` is empty

- **Gap details:** the table has 0 rows in SP_CLO. It links to a path, component and connection, but not to a `step_id`.
- **Impact:** gap display (UI-17) cannot be tested against real data. It is not clear how a gap would map to a step.
- **Suggested resolution:** provide a project that contains gaps, and add `step_id` (or `relation_id`) to `lineage_gap`.
- **Improvement expected in the UI:** gaps appear as warnings on the exact step they affect.

### EG-07 — `extraction_run` has no source identity

- **Gap details:** the single run has `source_file_name = unknown.brx` and a null `source_file_hash`.
- **Impact:** the UI cannot show which metadata export or version a lineage came from. The API detects a regenerated DB from the file's modification time and size.
- **Suggested resolution:** record the real source name and hash for each run.
- **Improvement expected in the UI:** a "generated from" line in the footer, and cache invalidation based on the run rather than on file attributes.

### EG-08 — Constants and functions are represented inconsistently

- **Gap details:** `CONSTANT_ASSIGNMENT` and `RUNTIME_FUNCTION_ASSIGNMENT` steps use a source object named `CONSTANT` or `FUNCTION` with `object_type = DataObject`, and the value in the column name (for example `"CLO"`, `Today( )`). `EXPRESSION` steps use an object with `object_type = CONSTANT`. `NOT_PERSISTED` steps use `Synthetic`.
- **Impact:** `object_type` of a terminal source does not reliably say whether it is a real table column or a constant. The UI has to look at the leaf relation type as well.
- **Suggested resolution:** use one representation: `object_type = CONSTANT` for constants and a separate type for functions, for every relation that produces them.
- **Improvement expected in the UI:** the right panel can label terminal sources (table column, constant, function, not persisted) from one field.

### EG-09 — No explicit parent link between steps

- **Gap details:** `business_lineage_step` has `path_id` and `lineage_level` but no parent. The API infers children as steps one level deeper in the same path whose target equals the step's source. This holds for all 320 steps in SP_CLO, with no orphans.
- **Impact:** if two steps in one path ever share an endpoint at the same level, their children would be shared.
- **Suggested resolution:** add `parent_step_id` to `business_lineage_step`.
- **Improvement expected in the UI:** navigation follows a stored link and no longer depends on the inference.

### EG-10 — `hop_count` is the step depth

- **Gap details:** `hop_count` equals `lineage_level + 1` on every row. It is the depth of the step, not the number of hops in the whole route.
- **Impact:** the hop count for the planned summary screen (target to ultimate source) has to be computed. The API cannot read it.
- **Suggested resolution:** keep `hop_count` as is and add a total-hops column on terminal steps, or rename the column.
- **Improvement expected in the UI:** the summary screen can show hops per target, column and source straight from the data.

### EG-11 — Same object name under several `source_project` values

- **Gap details:** `PAR_UNPROCESSED_EVENTS` and `PAR_UNPROCESSED_TRADES` each exist twice, with `source_project` `SP_CLO` and `GP_SHARED`. Both copies have the same Business Process. The `GP_SHARED` copies have one target column each.
- **Impact:** a name alone does not identify the object. The Target Object list shows `source_project` to tell them apart.
- **Suggested resolution:** provide a display name or qualified name for objects that share a name, and confirm why a `GP_SHARED` copy appears as a target here.
- **Improvement expected in the UI:** clearer labels in the selector, and no confusion about which object a Business Analyst is viewing.
