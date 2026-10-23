# Extractor Requirement: Resolved Business Process Invocations

## 1. Purpose

Materialize Aptitude Business Process calls as explicit, queryable edges. The current database contains the `business_process_invocation` table but has zero rows. Consumers therefore have to infer caller relationships from component names, which is fragile and can omit mappings from target-producing processes.

The extractor must populate this table from Aptitude Block components that reference Business Processes. This is a process-call relationship, not a column mapping: it supplements `column_relation` and `business_lineage_step`; it does not replace or duplicate either table.

## 2. Source Records

Create one invocation record for each component satisfying all of these conditions:

- `component.component_type = 'AptitudeServiceBlock'`
- `component.referenced_element_type = 'BusinessProcess'`
- `component.referenced_element_name` is present
- the calling component belongs to an extracted `business_process`

Do not create invocation records for RuleCall, TransformationNode, Target, Source, Routing, or other component types. Those are not Business Process calls.

Record each Block call independently. Two Block components that call the same Business Process are two invocation rows; do not collapse them by caller/callee pair. Preserve inactive Blocks too so the invocation table remains a faithful inventory. Consumers can join `component.is_active` when deciding which calls participate in active lineage.

## 3. Column Mapping

The existing table is the required output contract:

| `business_process_invocation` column | Extractor value |
|---|---|
| `invocation_id` | Stable deterministic ID for this call component; recommended `INV_` plus a hash of `call_component_id`. It must remain stable across identical re-extractions. |
| `calling_business_process_id` | `component.business_process_id`. |
| `call_component_id` | `component.component_id`. Exactly identifies the Aptitude Block. |
| `referenced_business_process_name` | `component.referenced_element_name`, preserved as authored after the extractor's normal whitespace normalization. |
| `referenced_project_name` | `component.referenced_project_name`. Preserve the referenced project; do not substitute a same-named process from the caller's project. |
| `referenced_business_process_id` | The resolved ID from `business_process`, when resolution is unique. Null otherwise. |
| `resolution_status` | One of the statuses in section 4. |
| `evidence_id` | Evidence supporting the Block reference, when available; otherwise null. Do not fabricate evidence. |

The referenced process is resolved by the exact pair:

```text
business_process.project_name = component.referenced_project_name
business_process.business_process_name = component.referenced_element_name
```

Do not resolve by process name alone: different projects can contain same-named processes.

If Aptitude omits a project qualifier, use the caller's project only when the source format explicitly defines an unqualified reference as same-project. Otherwise preserve the call as unresolved and record the reason; do not guess.

## 4. Resolution Statuses

Use these exact status values consistently:

- `RESOLVED`: exactly one process matches the referenced project/name pair; `referenced_business_process_id` is set.
- `UNRESOLVED`: no matching process is present in this extraction; `referenced_business_process_id` is null.
- `AMBIGUOUS`: more than one process matches the pair; `referenced_business_process_id` is null.

Every source Block still gets an invocation row, including unresolved and ambiguous calls. For unresolved/ambiguous cases, also write an `extraction_issue` with the call component/evidence and a useful diagnostic. Never pick an arbitrary candidate.

## 5. Idempotence and Integrity

- Re-extracting unchanged input must produce the same invocation IDs and rows.
- A component has at most one invocation row because each Aptitude Block names one referenced process. Enforce this with a unique constraint/index on `call_component_id` in addition to the primary key on `invocation_id`.
- `calling_business_process_id` and `call_component_id` must reference existing rows; the component's `business_process_id` must equal `calling_business_process_id`.
- When status is `RESOLVED`, the referenced ID must exist and match both stored referenced name and project.
- When status is `UNRESOLVED` or `AMBIGUOUS`, the referenced ID must be null.
- Replace/rebuild the invocation set transactionally with the rest of the extraction output. Do not leave stale rows when a Block is removed or its reference changes.

Suggested indexes for consumers:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_invocation_call_component
    ON business_process_invocation(call_component_id);
CREATE INDEX IF NOT EXISTS idx_invocation_resolved_target
    ON business_process_invocation(referenced_business_process_id, resolution_status);
CREATE INDEX IF NOT EXISTS idx_invocation_caller
    ON business_process_invocation(calling_business_process_id);
```

If existing databases may contain duplicate calls, detect and report them before creating the unique index rather than silently discarding a row.

## 6. SP_LIQ Example

The current SP_LIQ database contains an Aptitude Target component for `PAR_GFRS_LIQ_TRADES` in Business Process `PAR_GFRS_LIQ_TRADES`:

```text
Target BP: BPR_7bc39e6af53dd7f4537387108f87b7cc16665f2176813e2a07492126e539c617
Target component: CMP_bc4dd42af979444739437b4ba46276e331b499e88b36887850e18170fbb3e89e
Target project/name: SP_LIQ / PAR_GFRS_LIQ_TRADES
```

Twelve other Business Processes contain `AptitudeServiceBlock` components that reference that exact BP. Two expected invocation records are:

| Caller Business Process | Block component | Referenced process | Resolved ID | Status |
|---|---|---|---|---|
| `CM_LIQ_AMRT_ADMIN_FEE` (`BPR_52b68fccd5e8e18d2ea63e3b29df6a897c042ffbaa1a2907e466597516a1af53`) | `CMP_09bcd58bd81218c9cbe4bd98ac1863252165be49e38ec1938ce9cde4eb3f4efa` | `SP_LIQ / PAR_GFRS_LIQ_TRADES` | `BPR_7bc39e6af53dd7f4537387108f87b7cc16665f2176813e2a07492126e539c617` | `RESOLVED` |
| `CM_LIQ_PROVISION_BAL` (`BPR_dc65513fad8730e040bda1f9a33899d1a64162e832aaeb0657714393fd038a88`) | `CMP_d649c772fa983ab4566b69f3c6f06392359a5fa0a3fadc951263e45e191d5744` | `SP_LIQ / PAR_GFRS_LIQ_TRADES` | `BPR_7bc39e6af53dd7f4537387108f87b7cc16665f2176813e2a07492126e539c617` | `RESOLVED` |

For each row, the extractor copies the caller ID, component ID, referenced name and project from the source records, resolves the referenced ID using the exact pair, computes a stable invocation ID, and sets `evidence_id` if source evidence is available.

## 7. Consumer Contract

A Target's lineage roots are the roots belonging to:

1. the Business Process that owns the `AptitudeServiceTarget` component; and
2. each caller Business Process whose invocation resolves to that Target Business Process.

Only resolved invocations participate in traversal. Use `referenced_business_process_id` to join; do not rediscover calls from matching component names. Keep the caller's root target object/column IDs and mapping rows intact when combining the logical Target view.

This allows the target summary, graph, and walkthrough to include mappings written by all calling processes while retaining the originating Business Process on each mapping.

## 8. Acceptance Checks

For SP_LIQ:

- There is one invocation row for every `AptitudeServiceBlock` referencing a Business Process: currently 12 for calls to `PAR_GFRS_LIQ_TRADES` alone.
- Each of those 12 resolves uniquely to the `PAR_GFRS_LIQ_TRADES` BP ID above.
- The Target summary for `PAR_GFRS_LIQ_TRADES` includes caller mappings such as `ACC_AMT_ADJ` from `CM_LIQ_AMRT_ADMIN_FEE`, `CM_LIQ_PORTF_ACCRUAL`, and other callers; it must not show those columns as having no lineage when root steps exist.
- Unresolved and ambiguous references remain visible in the invocation table, have null referenced IDs, and produce extraction issues.
- Re-running extraction is idempotent and does not duplicate invocation rows.
- A fixture with two projects containing the same Business Process name resolves by project; a missing target remains `UNRESOLVED`; duplicate same-project process names are `AMBIGUOUS`.

## 9. Current Repository Boundary

This repository contains the generated SP_LIQ SQL/database artifacts and the read-only lineage API, but not the program that extracts Aptitude data. The API-side target resolver currently supplements the empty invocation table by inspecting Block components. Once the extractor populates `business_process_invocation`, the consumer should switch to that table and retain the current fallback only for older databases during migration.
