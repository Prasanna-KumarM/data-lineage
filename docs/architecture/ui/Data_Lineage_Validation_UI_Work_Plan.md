# Data Lineage Validation UI — Implementation Work Plan

## 1. Purpose

This work plan translates the approved **Data Lineage Validation UI** design into an implementation sequence that can be executed one task at a time.

The product goal is a **target-centric, single-branch, hop-by-hop lineage validator**. The validator keeps the original target visible, presents only the immediate upstream choices for the current endpoint, and allows the user to follow one selected branch toward its ultimate source. The UI must consume generated lineage data; it must not become a second lineage engine.

### Approved design decisions

- Visible selectors: **Project**, **Target Object**, **Target Column**.
- Left panel: fixed original target.
- Middle panel: immediate upstream lineage choices for the current endpoint.
- Right panel: **ultimate terminal source(s)** for the selected target/branch.
- Ultimate terminal sources are fetched when the target column is selected and cached for the active target/session.
- Navigation follows **one selected branch at a time**.
- Completed hops are shown as filled dots; known remaining hops as hollow dots; uncertain/variable remaining depth as an ellipsis or range.
- Remaining-hop depth is calculated **only for the active selected branch**.
- `business_process_id` and `business_process_name` are added to `business_lineage_step` as read-model/reporting fields; canonical `column_relation` remains authoritative.
- SQLite remains the lineage source of truth; the browser communicates through a backend API using small JSON responses.
- Authentication/audit design and full raw BRX-evidence coverage are explicitly deferred from this work plan.

---

## 2. Global implementation boundaries

These boundaries apply to every task unless a task explicitly says otherwise.

### In scope

- Read-only lineage navigation over generated `lineage.db` data.
- Read-model updates required by the approved UI.
- Backend API endpoints required by the UI.
- UI implementation for target selection, single-branch navigation, progress rail, source preview, and relation details.
- Separate validation records for reviewer findings.
- Focused unit/integration tests and golden-project validation.

### Out of scope

- Changing BRX parsing semantics solely for UI convenience.
- Editing canonical lineage from the UI.
- Reintroducing recursive BRX parsing in the UI or browser.
- Reintroducing complete-path explosion to support navigation.
- Authentication/authorization architecture.
- Full raw-BRX document viewer/evidence browser.
- A force-directed full lineage graph as the primary UI.
- Replacing SQLite as the canonical generated lineage store.

### Core non-negotiable rule

If the UI exposes incorrect lineage, the fix belongs in extraction/canonical lineage generation. The UI may report the issue but must not suppress or rewrite canonical lineage.

---

# Phase A — Read Model and Database Readiness

## UI-01 — Freeze the UI lineage contract and baseline

### Objective
Create a reproducible baseline before UI-specific schema or API changes.

### Scope
- Document the current `business_lineage_step`, `column_relation`, canonical object/column, component, confidence, dependency, and gap fields used by the UI.
- Capture representative results for the golden projects.
- Preserve the validated distinct-step behavior, including the known regression where `SP_LIQ / AR_PAR_FEE_EVENTS / CONTRACT_ID` matches the trusted SQL result.

### Deliverables
- Baseline field contract.
- Baseline SQL queries used for regression comparison.
- Focused tests proving the existing distinct-step materialization remains deterministic.

### Boundaries
- No UI code.
- No schema changes.
- No lineage semantic changes.

### Acceptance criteria
- Existing lineage unit/integration tests pass.
- Representative target queries are repeatable.
- Existing step IDs remain deterministic across repeated generation with the same metadata.

### Depends on
None.

---

## UI-02 — Add Business Process fields to `business_lineage_step`

### Objective
Expose Business Process directly in the UI read model so the API does not repeatedly rediscover it through component joins.

### Scope
Add:

- `business_process_id`
- `business_process_name`

through the full business-step pipeline:

- `BusinessLineageStep` model
- materializer population
- SQLite table DDL
- SQLite insert
- read/query tests

### Deliverables
- Updated persisted `business_lineage_step` rows containing both fields.
- Unit tests for deterministic population.
- Integration validation on representative SP_LIQ/SP_CLO rows.

### Boundaries
- Do not move Business Process ownership into `column_relation` if it is not already canonical there.
- Do not change traversal semantics.
- Do not change business-process filtering rules that were already validated against SQL.

### Acceptance criteria
- Every UI-targeted step has the expected Business Process fields where component metadata provides them.
- Existing `CONTRACT_ID` distinct-step regression remains unchanged except for the two added columns.
- SQLite foreign-key/integrity checks remain green.

### Depends on
UI-01.

---

## UI-03 — Target catalog read model

### Objective
Provide an efficient source for the three selector controls: Project, Target Object, Target Column.

### Scope
Define read queries/services that return:

1. available projects;
2. business target objects restricted to the approved `AptitudeServiceTarget` population;
3. target columns belonging to the selected target object and having lineage data.

### Deliverables
- Repository/service queries for projects, target objects, and target columns.
- Deterministic ordering rules.
- Tests covering same object names across different projects.

### Boundaries
- Do not add a second target-classification rule.
- Do not make the frontend interpret component types to decide what is a target.

### Acceptance criteria
- Project selection disambiguates same-named objects across projects.
- Target Object lists only the approved business target population.
- Target Column selection returns only columns relevant to validation.

### Depends on
UI-01.

---

# Phase B — Lineage Navigation Services

## UI-04 — Immediate-upstream navigation query/service

### Objective
Return exactly the selectable middle-panel mappings feeding the current endpoint.

### Scope
Input:

- project/current lineage DB
- current `object_id`
- current `column_id`
- Business Process context where required

Output per choice:

- `step_id`
- `relation_id`
- relation type
- source object/column IDs and names
- target object/column IDs and names
- component ID/name/type
- Business Process ID/name
- confidence class/reason
- traversal path
- driving expression
- result expression
- whether more upstream relations exist
- immediate upstream-choice count

### Deliverables
- Backend repository/service function returning immediate upstream choices.
- Stable response DTO/schema.
- Unit tests for branching, terminal endpoints, expression branches, constants, and enrichment.

### Boundaries
- No complete-path enumeration.
- Do not fetch sibling branches after the user has selected one branch except when returning to a previous navigation state.
- Do not derive lineage from names when canonical object/column IDs are available.

### Acceptance criteria
- Starting from a target with `p1`, `p2`, `p3`, the service returns exactly those immediate choices.
- Starting from `p1.source`, the service returns only `p1.1`, `p1.2`, not `p2.1` or `p3.1`.
- Business Process constraints match the validated distinct-step traversal semantics.

### Depends on
UI-02, UI-03.

---

## UI-05 — Ultimate terminal-source resolver and target cache

### Objective
Support the approved right panel: ultimate terminal sources reachable from the selected target/branch.

### Scope
- On target-column selection, compute/fetch the terminal-source information required for the right panel.
- Cache the result for the active target/session.
- Associate terminal source(s) with the branch choices required to filter the cache after `p1`, `p1.2`, etc. are selected.
- Return terminal source endpoint, terminal classification, and enough branch identity to filter without rescanning the entire project.

### Deliverables
- Terminal-source resolver service.
- Session/target-scoped cache abstraction.
- Cache invalidation rule: new target selection or changed lineage DB/version clears/replaces the target cache.
- Tests with branching example:
  - p1 -> p1.1.1, p1.2.1
  - p2 -> p2.1.1, p2.1.2, p2.1.3
  - p3 -> p3.1.1

### Boundaries
- Do not materialize or send the whole project graph to the browser.
- Do not rebuild lineage from BRX.
- Do not make terminal-source cache the canonical lineage store.

### Acceptance criteria
- Initial target can show all ultimate sources.
- Selecting p1 filters the right panel only to terminal sources reachable through p1.
- Selecting p1.2 filters to p1.2.1 in the worked example.
- Cache data is deterministic for a fixed lineage DB.

### Depends on
UI-04.

---

## UI-06 — Active-branch remaining-depth service

### Objective
Calculate the right-side hop indicator only for the branch actively selected by the user.

### Scope
Return one of:

- exact remaining hop count;
- minimum/maximum depth range when terminal routes have different lengths;
- terminal/no remaining hops.

### Deliverables
- Depth calculation service operating on the active branch only.
- API response fields such as:
  - `remaining_hops_exact`
  - or `remaining_hops_min` / `remaining_hops_max`
- Tests for exact depth, variable depth, terminal source, and cycle-safe behavior.

### Boundaries
- Do not eagerly calculate remaining depth for every middle-panel choice before selection.
- Do not recreate complete-path cross-products.
- Remaining-hop information is presentation data, not canonical relation identity.

### Acceptance criteria
- Known exact depth produces the corresponding hollow-dot count.
- Variable depth produces a range/ellipsis state.
- Terminal source produces zero remaining hops.

### Depends on
UI-04, UI-05.

---

## UI-07 — Relation/detail service

### Objective
Provide the detail drawer used by business validators and developers without cluttering the main navigation cards.

### Scope
Return for a selected relation/step:

- source endpoint
- target endpoint
- relation type
- component
- Business Process
- confidence and reason
- traversal path
- driving expression
- result expression
- relation ID
- step ID
- expression ID when present
- dependency-role summary if available
- gap/persistence explanation when applicable

### Deliverables
- Relation-detail API/service.
- Response schema.
- Tests for explicit mapping, expression, enrichment, constant/function synthetic source, and `NOT_PERSISTED`.

### Boundaries
- Raw BRX evidence browser is deferred.
- Do not expose implementation-only Python objects directly to the frontend.

### Acceptance criteria
- Expression details clearly distinguish condition/control from value/result expression.
- `NOT_PERSISTED` details expose the canonical reason available in the generated lineage data.

### Depends on
UI-02.

---

# Phase C — Backend API

## UI-08 — Build the read-only lineage API skeleton

### Objective
Create the backend boundary between the browser and SQLite.

### Scope
Recommended implementation: Python API service consistent with the existing Python codebase. The concrete framework can be chosen during implementation; the contract is framework-independent.

Expose endpoints for:

- `GET /projects`
- `GET /targets?project=...`
- `GET /targets/{object}/columns`
- `GET /lineage/upstream`
- `GET /lineage/ultimate-sources`
- `GET /lineage/remaining-depth`
- `GET /relations/{relation_id}`

### Deliverables
- API application skeleton.
- SQLite connection/repository boundary.
- Typed request/response schemas.
- Error response conventions.
- API tests using a controlled lineage database fixture.

### Boundaries
- Browser must not connect directly to SQLite.
- API must not execute lineage extraction.
- API must not mutate canonical lineage.
- Validation write APIs are handled in a later task.

### Acceptance criteria
- Browser-consumable JSON is returned for all read endpoints.
- Invalid project/object/column/relation returns deterministic errors.
- SQLite details are not coupled into frontend contracts.

### Depends on
UI-03 through UI-07.

---

## UI-09 — API caching for target session data

### Objective
Make selector and branch navigation responses fast without introducing a second source of truth.

### Scope
Cache only read models that are expensive or repeatedly requested:

- project/target catalogs;
- ultimate-terminal-source data for the active target;
- optionally relation detail by stable relation ID.

### Deliverables
- In-memory cache abstraction for MVP.
- Cache key definition including project/lineage DB identity and target endpoint.
- Invalidation tests.

### Boundaries
- Do not generate one giant project JSON file for the browser.
- Cache is disposable and reconstructable from SQLite.
- Do not cache canonical mutations because the API does not perform them.

### Acceptance criteria
- Repeated branch operations on the same target do not recompute ultimate sources unnecessarily.
- Changing project/target invalidates/replaces target-scoped cached data.

### Depends on
UI-05, UI-08.

---

# Phase D — Frontend Navigation MVP

## UI-10 — Frontend shell and selector workflow

### Objective
Create the UI entry experience and load a target lineage session.

### Scope
Implement:

- Project dropdown
- Target Object dropdown
- Target Column dropdown
- loading/error/empty states
- reset navigation when any selector changes

### Deliverables
- Frontend application shell.
- API client layer.
- Selector components.
- Tests for selector dependencies and reset behavior.

### Boundaries
- No lineage graph rendering.
- No branch navigation yet.

### Acceptance criteria
- Project drives Target Object options.
- Target Object drives Target Column options.
- Target Column selection initializes lineage navigation data.

### Depends on
UI-08.

---

## UI-11 — Three-panel lineage layout

### Objective
Implement the fixed visual model: Target | Lineage Choice | Ultimate Source.

### Scope
- Fixed left target card.
- Middle choice-card container.
- Right ultimate-source panel.
- Responsive layout that preserves the three-region mental model.

### Deliverables
- Three-panel components.
- Styling tokens for relation types/statuses.
- Empty, terminal, and multi-source states.

### Boundaries
- No full graph.
- No automatic movement into a branch.
- The user must explicitly choose the branch to follow.

### Acceptance criteria
- Target remains unchanged as the user navigates.
- Middle renders only current immediate choices.
- Right renders cached ultimate source(s) applicable to the current target/selection.

### Depends on
UI-10.

---

## UI-12 — Single-branch navigation state machine

### Objective
Implement p1 -> p1.2 -> p1.2.1 behavior exactly as approved.

### Scope
Frontend state:

- selected target
- selected relation stack
- current endpoint
- current selected choice
- prior selections for Back/jump restoration

Interactions:

- select middle card
- Next
- Back
- reset on target change

### Deliverables
- Navigation state reducer/state machine.
- Integration with `/lineage/upstream`.
- Tests using the worked p1/p2/p3 branching fixture.

### Boundaries
- Do not display sibling routes after the user moves into a selected branch.
- Do not infer navigation from lineage levels alone; use canonical source/target endpoint IDs.

### Acceptance criteria
- Initial middle: p1, p2, p3.
- Select p1 + Next: middle becomes p1.1, p1.2 only.
- Select p1.2 + Next: middle/source state reflects only p1.2 branch.
- Back restores the exact prior choices and selected relation.

### Depends on
UI-04, UI-11.

---

## UI-13 — Hop progress rail and breadcrumb

### Objective
Give validators compact context about traversed and remaining depth without expanding previous/future hops.

### Scope
- `●` one per completed selected hop.
- optional `◉` for current position.
- `○` for exact remaining hops on the active branch.
- `⋯` or range for variable remaining depth.
- completed dots clickable to restore earlier states.
- tooltip/focus text describing hop, endpoint, relation type.
- textual breadcrumb retained for accessibility and precision.

### Deliverables
- Progress rail component.
- Breadcrumb component.
- Accessibility labels/keyboard interaction.
- Tests for exact, variable, and terminal depth states.

### Boundaries
- Unselected sibling mappings never become dots.
- Remaining depth is not calculated for every unselected choice.

### Acceptance criteria
- Selecting p1 creates one completed dot, not three dots for p1/p2/p3.
- Selecting p1.2 creates a second completed dot.
- Clicking the first completed dot returns to the p1 state.

### Depends on
UI-06, UI-12.

---

## UI-14 — Mapping cards and relation detail drawer

### Objective
Make each branch choice independently understandable and verifiable.

### Scope
Mapping card shows:

- source object/column
- relation type
- confidence
- component
- upstream-choice count
- selection state

Detail drawer shows the UI-07 data contract.

### Deliverables
- Card component.
- Relation-type badge system.
- Detail drawer.
- Developer-detail toggle.

### Boundaries
- Do not put every technical ID on the default card.
- Do not hide driving/result expressions for expression relations.

### Acceptance criteria
- Separate CASE branches remain separate when their expression metadata differs.
- Expression details visibly distinguish condition from value expression.
- Constants/functions/NOT_PERSISTED are visually distinguishable.

### Depends on
UI-07, UI-11.

---

# Phase E — Validation Feedback

## UI-15 — Validation data model and storage

### Objective
Store reviewer findings without modifying canonical lineage.

### Scope
Create a separate validation model/table containing at minimum:

- validation ID
- project
- root target object/column IDs
- relation ID and/or step ID when applicable
- status: `UNREVIEWED`, `VALID`, `NEEDS_INVESTIGATION`, `INCORRECT`
- issue type
- comment
- basic created/updated fields required by the application

### Deliverables
- Validation table/model.
- SQLite or separate application-store persistence according to the chosen deployment packaging.
- CRUD repository tests.

### Boundaries
- Do not change `column_relation`, `business_lineage_step`, or other canonical lineage records based on reviewer input.
- Authentication architecture remains out of scope.

### Acceptance criteria
- A reviewer can save and reload a finding tied to a target and optionally a specific relation/step.
- Regenerating canonical lineage does not silently rewrite reviewer decisions; any reconciliation rule must be explicit.

### Depends on
UI-01.

---

## UI-16 — Validation interactions in the UI

### Objective
Allow users to mark the selected target/step as valid, needs investigation, or incorrect.

### Scope
- Status controls.
- Issue categories such as wrong source, missing source, wrong expression, wrong persistence status, wrong relation, other.
- Comment field.
- Display saved review status when revisiting the target/relation.

### Deliverables
- Validation controls.
- API write/read endpoints.
- UI tests.

### Boundaries
- No canonical lineage mutation.
- No authentication/authorization work in this task.

### Acceptance criteria
- Validation feedback can be saved and retrieved.
- Selecting `INCORRECT` does not change the lineage displayed from canonical data.

### Depends on
UI-15, UI-14.

---

# Phase F — Edge Cases and Application Hardening

## UI-17 — Synthetic sources, gaps, and exceptional lineage states

### Objective
Ensure special canonical lineage constructs are understandable and safe in the branch navigator.

### Scope
Handle:

- `CONSTANT`
- `FUNCTION`
- `NOT_PERSISTED`
- `LineageGap`
- no-upstream terminal DataObject column
- cycle-prevented state

### Deliverables
- Presentation rules implemented and tested.
- Terminal/Next-button behavior.
- Clear labels/reasons where canonical data provides them.

### Boundaries
- Do not invent missing endpoints.
- Do not reinterpret `NOT_PERSISTED` in UI logic.

### Acceptance criteria
- Terminal constructs stop navigation cleanly.
- Gap states show warnings rather than fabricated lineage.
- Constants and functions preserve the approved expression semantics.

### Depends on
UI-12, UI-14.

---

## UI-18 — Enrichment/traversal variants and same-endpoint branches

### Objective
Preserve legitimate relation choices that differ by traversal or rule semantics even when endpoints are identical.

### Scope
- Distinct `step_id` rows.
- traversal-path variants.
- same endpoint with different driving/result expressions.
- same relation reached through distinct SQL-projected lineage steps.

### Deliverables
- Card disambiguation labels/details.
- Regression tests using enrichment cases observed during SP_LIQ validation.

### Boundaries
- Do not deduplicate by endpoint alone.
- Do not collapse rows that the trusted distinct-step SQL considers different.

### Acceptance criteria
- Legitimate traversal-path variants remain selectable/inspectable.
- UI keying uses stable step/relation identity without React/render collisions.

### Depends on
UI-14, UI-17.

---

## UI-19 — Performance and resilience validation

### Objective
Verify that UI responsiveness comes from narrow indexed queries and targeted caching, not from moving the full graph into the browser.

### Scope
- Measure selector load, immediate-upstream query, ultimate-source cache load, active-branch depth query, relation detail query.
- Confirm database indexes support those queries.
- Test larger golden-master projects including SP_LIQ.
- Test cache invalidation/error states.

### Deliverables
- Performance test/report with measured results from the implemented environment.
- Any required query/index changes.
- Resilience tests for unavailable/corrupt/mismatched lineage DB.

### Boundaries
- Do not introduce speculative caching layers before measurements justify them.
- Do not compromise lineage correctness to reduce counts.

### Acceptance criteria
- No browser operation requires downloading an entire project lineage graph.
- No navigation operation re-parses BRX metadata.
- Any performance optimization preserves returned lineage rows exactly.

### Depends on
UI-09 through UI-18.

---

# Phase G — Golden-Master Validation and Handoff

## UI-20 — End-to-end functional validation on golden projects

### Objective
Validate the implemented UI against the lineage datasets used as project quality baselines.

### Scope
Run supported end-to-end validation flows on:

- SP_CLO
- SP_LIQ
- GP_CLO
- GP_LEND

Include representative cases for:

- simple explicit mapping
- branching expression lineage
- constants
- enrichment lookup
- terminal DataObject source
- NOT_PERSISTED where canonically valid
- Business Process isolation

### Deliverables
- Functional validation checklist/results.
- Defects classified as UI/API issue versus canonical lineage issue.
- Regression target list for future releases.

### Boundaries
- UI defects are fixed in UI/API.
- Canonical lineage defects are returned to extraction/canonical work; do not compensate in UI.

### Acceptance criteria
- Representative targets navigate consistently and deterministically.
- Branch selection and source preview match canonical lineage data.
- No project-specific hardcoded lineage rules exist in UI code.

### Depends on
UI-19.

---

## UI-21 — Documentation, operating guide, and implementation cleanup

### Objective
Leave the validation UI maintainable and ready for iterative task-by-task development.

### Scope
- Final API contract.
- Data-model/read-model documentation.
- Frontend navigation-state documentation.
- How to add relation types/edge-case renderers.
- How to run tests.
- How to generate/use lineage DBs.
- Remove temporary debug logs and diagnostic switches.

### Deliverables
- Contributor/implementation guide.
- Updated approved design references.
- Release checklist.

### Boundaries
- Documentation must reflect implemented behavior; it must not redefine lineage semantics.

### Acceptance criteria
- A developer can run the UI against a generated lineage DB using documented steps.
- No temporary target-specific filters or diagnostics remain in production code.

### Depends on
UI-20.

---

# 3. Recommended implementation order

Execute tasks strictly in this order unless a failing acceptance criterion requires returning to an earlier task:

```text
UI-01  Baseline
  |
UI-02  Business Process read-model fields
  |
UI-03  Target catalog
  |
UI-04  Immediate upstream service
  |
UI-05  Ultimate-source resolver/cache
  |
UI-06  Active-branch remaining depth
  |
UI-07  Relation details
  |
UI-08  API skeleton
  |
UI-09  API caching
  |
UI-10  Frontend selectors
  |
UI-11  Three-panel layout
  |
UI-12  Single-branch navigation
  |
UI-13  Hop rail + breadcrumb
  |
UI-14  Cards + detail drawer
  |
UI-15  Validation store
  |
UI-16  Validation interactions
  |
UI-17  Synthetic/gap states
  |
UI-18  Traversal variants
  |
UI-19  Performance/resilience
  |
UI-20  Golden-master validation
  |
UI-21  Documentation/handoff
```

---

# 4. Definition of done for each task

A task is complete only when all of the following are true:

1. **Scope implemented:** every item explicitly listed under Scope is complete.
2. **Deliverables exist:** code/schema/documents/tests described under Deliverables are present.
3. **Boundaries respected:** no out-of-scope behavior was added to make the task pass.
4. **Focused tests pass:** task-specific unit/integration tests are green.
5. **Regression preserved:** existing lineage behavior outside the task remains green.
6. **No temporary workaround:** no project-specific or target-specific workaround is left behind.
7. **Reviewable delta:** the task can be independently reviewed before starting the next task.

---

# 5. Working rule for task-by-task execution

For each task:

1. Re-read the task objective, scope, deliverables, boundaries, and acceptance criteria.
2. Inspect the current code before changing it.
3. Implement only that task.
4. Add focused tests before proceeding.
5. Run focused tests, then the appropriate regression suite.
6. Record any discovered canonical-lineage defect separately rather than compensating in UI code.
7. Stop after the task is green and review the result before beginning the next task.

This work plan intentionally favors small, testable increments over a single large UI implementation.
