# Extractor Requirement: Cross-Stage Lineage (FPL to PAR, PAR Processing, PAR to GFRS)

## 1. Purpose

Show the complete data flow, not only the Aptitude mappings of one project. The flow is split into stages. Each stage is extracted into its own project database, in the same format as `SP_CLO` and `SP_LIQ`.

| Stage code | Meaning | Position |
|---|---|---|
| `FPL_TO_PAR` | FPL to PAR | previous |
| `PAR_PROCESSING` | PAR Processing (the stage shown today: `SP_CLO`, `SP_LIQ`, ...) | focus |
| `PAR_TO_GFRS` | PAR to GFRS | next |

Users stay in `PAR_PROCESSING`. From a column they can go back to see where it comes from in `FPL_TO_PAR`, or go forward to see what consumes it in `PAR_TO_GFRS`.

The stages are linked by the identity of the tables and columns they share. No separate link store is needed, provided the identity rules in section 4 hold across all databases.

## 2. What the current databases show

| Finding | Evidence |
|---|---|
| An object's id depends on its project scope (`source_project`) and name. | `PAR_UNPROCESSED_TRADES` in scope `GP_SHARED` has the same `object_id` (`OBJ_3cc51995ffc2236c...`) in `SP_CLO` and `SP_LIQ`. In scope `SP_CLO` or `SP_LIQ` the same name gets a different id in each database. |
| Column ids follow the object id, so a shared object gives shared columns. | 3 column ids are common to both databases, all in shared objects. |
| The same physical table can have two ids in one database. | In `SP_LIQ`, `CM_PAR_LOAN_TRADES` exists as `OBJ_2d5f8a52543f...` (scope `SP_LIQ`, 271 mappings as target) and as `OBJ_046005a7bf65...` (scope `GP_SHARED`, 67 as target, 3 as source). |
| A table written in one project and read in another does not match today. | `CM_PAR_LOAN_TRADES` is a target in `SP_CLO` (`OBJ_2a471444abc7...`, scope `SP_CLO`) and appears as a source in `SP_LIQ` under another id. |
| The databases hold no stage information. | `canonical_object` has only name, type and `source_project`. `extraction_run` has no stage. |

## 3. Output: stage of each database

New table `lineage_stage`, one row per database:

| Column | Value |
|---|---|
| `stage_code` | One of the codes in section 1. |
| `stage_name` | Display name, for example `PAR Processing`. |
| `stage_order` | 1 for `FPL_TO_PAR`, 2 for `PAR_PROCESSING`, 3 for `PAR_TO_GFRS`. |
| `project_name` | The project of this database, equal to `business_process.project_name`. |

Several databases can belong to the same stage (`SP_CLO` and `SP_LIQ` are both `PAR_PROCESSING`).

## 4. Identity rules for shared objects

1. **One id per physical table or file.** A table or file that is written by one stage and read by another, or that is shared between projects of a stage, must get the same `object_id` in every database. The id is built from a stable shared namespace and the table name, never from the project that happens to read or write it. `GP_SHARED` already does this, and it should be applied to every boundary object.
2. **One id per object inside a database.** The same table must not appear under two ids in one database. In `SP_LIQ`, `CM_PAR_LOAN_TRADES` must be one object.
3. **Column ids follow the object.** A column is identified by its object id and column name, so a shared object gives the same `column_id` everywhere.
4. **Column names match.** A column that exists in both stages has the same `column_name` on both sides. Links are at column level only.

Example: `PAR_UNPROCESSED_TRADES` as seen today in `SP_CLO` and `SP_LIQ` already follows these rules. `CM_PAR_LOAN_TRADES` does not.

## 5. Output: boundary objects

New table `boundary_object`, one row per shared object per database:

| Column | Value |
|---|---|
| `object_id` | The shared id, as in section 4. |
| `direction` | `PRODUCES` if this database writes the object (it is a target of a mapping here), `CONSUMES` if this database reads it (it is a source here). An object can be both. |
| `stage_code` | The stage of this database. |
| `physical_name` | The table or file name as the owning system knows it. |

One row per (`object_id`, `direction`). Every object listed here must exist in `canonical_object`. Every shared object used as a mapping source or target must be listed.

## 6. Checks across databases

The extraction team (or a script run after extraction) must verify across all databases:

- Every `CONSUMES` object of a database has a `PRODUCES` row with the same `object_id` in some database of an earlier stage, or of the same stage. Objects without one are reported as origin not available.
- Every column of a consumed object that is used as a source exists in the producing object. Missing columns are reported.
- No physical name appears under two ids in one database or across databases.

## 7. How the consumer uses it

- The API reads `lineage_stage` and `boundary_object` from every database when the registry loads, and keeps a map from `object_id` to the databases that produce or consume it. It is rebuilt only when a database file changes.
- Going back: an ultimate source of a `PAR_PROCESSING` graph that is a `CONSUMES` boundary object is looked up in the databases of an earlier stage. The upstream graph of the same `column_id` is shown there.
- Going forward: a `PRODUCES` column of `PAR_PROCESSING` is looked up in the databases of a later stage, where it is a mapping source. The mappings that use it are followed downstream.
- No operand-style precomputation is required for the first version. Downstream traversal can be added to the API with a reverse index on `source_column_id`.

## 8. Acceptance checks

- Each database has exactly one `lineage_stage` row.
- `PAR_UNPROCESSED_TRADES` keeps its id in every database, and is listed as `PRODUCES` in the stage that writes it and as `CONSUMES` where it is read.
- `CM_PAR_LOAN_TRADES` has a single `object_id` in `SP_LIQ`, and the same id in `SP_CLO` and `SP_LIQ`, with `PRODUCES` in `SP_CLO` and `CONSUMES` in `SP_LIQ`.
- A fixture with a table written in an `FPL_TO_PAR` database and read in a `PAR_PROCESSING` database links by `object_id` and `column_id`. A fixture with a consumed object that has no producer is reported as origin not available.
- Re-extracting unchanged input gives identical ids.

## 9. Current repository boundary

This repository holds the generated databases and the read-only API, not the extractor. Until the extractor emits the two tables and the shared ids, the API and UI can only show `PAR_PROCESSING` as they do today.
