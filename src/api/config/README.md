# Business catalog (`catalog.csv`)

The catalog translates technical project codes into the vocabulary business users
know, and decides which tables the business view of the summary page lists.

## What it does

Each row maps one project (one `outputs/<PROJECT>/lineage.db`) to:

| Column | Meaning |
| --- | --- |
| `project` | Project code = the folder name under `outputs/` (e.g. `SP_LIQ`). Required. |
| `value_chain` | Business area, e.g. `Lending`. Becomes a filter on the summary page. |
| `source_system` | The system the data is read from, e.g. `Loan IQ`. |
| `target_system` | The system the tables feed, e.g. `GFRS`. Becomes a filter on the summary page. |
| `tables` | `|`-separated whitelist of the tables shown to business users, e.g. `PAR_GFRS_TFS_TRADES\|PAR_GFRS_TFS_CHARGES`. Empty = nothing shown to business for this project. |

Effects in the UI:

- The summary landing page gets a **Business** view (the default when a catalog
  exists): only the whitelisted tables, filterable by value chain and target
  system, with the subtitle `value_chain · source_system · target_system · project`.
  The **Developer** view keeps listing every table of every project.
- The **first data row** preselects the value chain / target system filters.
- The same subtitle appears under the table name on the table summary page.

## Drift is reported, never silent

The API cross-checks the catalog against the databases and shows notes behind
the ⓘ icon:

- a whitelisted table missing from the project's database,
- a catalog row whose project has no database,
- a ready project with no catalog row (visible in the developer view only).

## How to configure it

- **Default location:** this file — `src/api/config/catalog.csv`. Edit and save;
  the API re-reads it automatically (no restart needed).
- **Override:** set the `LINEAGE_CATALOG` environment variable to another file
  path. The env var always wins.
- **Containers:** when the API image does not include this directory, mount the
  file into the container and point `LINEAGE_CATALOG` at it, e.g.
  `docker run -v ./catalog.csv:/config/catalog.csv -e LINEAGE_CATALOG=/config/catalog.csv ...`

## CSV tips

- Header row is required: `project,value_chain,source_system,target_system,tables`
- Use `|` (not commas) between tables — no quoting needed. If a value contains a
  comma, quote the cell: `"Risk, Treasury"`.
- Excel/UTF-8 BOM is handled.
- Blank lines and rows without a `project` are skipped.

## Example

```csv
project,value_chain,source_system,target_system,tables
SP_LIQ,Lending,Loan IQ,GFRS,PAR_GFRS_LIQ_TRADES
SP_TFS_TIP,Trade Finance,Ti Plus,GFRS,PAR_GFRS_TFS_TRADES|PAR_GFRS_TFS_CHARGES
SP_CLO,Lending,CLO,GFRS,PAR_GFRS_CLO_TRADES
```
