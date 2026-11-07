"""Read-only lineage API: the boundary between the browser and the SQLite lineage DB."""
import os
import sqlite3
from typing import Iterator, Optional

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from lineage_api import schemas
from lineage_api.catalog import list_projects, list_target_columns, list_target_objects, search_target_objects
from lineage_api.continuations import find_continuations
from lineage_api.export import build_table_workbook
from lineage_api.db import (
    ENV_DB_PATH,
    DatabaseNotConfigured,
    DatabaseUnavailable,
    SchemaMismatch,
    check_schema,
    open_readonly,
)
from lineage_api.depth import get_remaining_depth
from lineage_api.detail import RelationNotFound, get_relation_detail, get_step_detail
from lineage_api.lineage_graph import build_column_graph, build_target_graph
from lineage_api.analysis_stats import AnalysisStatsCache
from lineage_api.business_catalog import BusinessCatalog
from lineage_api.projects import ENV_OUTPUTS_DIR, ProjectRegistry
from lineage_api.sources import TargetSourceCache, sources_for_step
from lineage_api.summary import TableSummaryCache
from lineage_api.target_catalog import (
    TargetCatalogCache,
    _has_target_components,
    find_target,
    list_target_columns as list_target_component_columns,
    target_definitions,
    summarize_target,
    target_column_pairs,
)
from lineage_api.upstream import StepNotFound, get_root_choices, get_upstream_choices


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _registry(request: Request) -> Optional[ProjectRegistry]:
    """Set when databases are found in <outputs>/<project>/lineage.db instead of one fixed file."""
    if request.app.state.db_path or os.environ.get(ENV_DB_PATH):
        return None
    directory = request.app.state.outputs_dir or os.environ.get(ENV_OUTPUTS_DIR)
    if not directory:
        return None
    return request.app.state.registries.setdefault(str(directory), ProjectRegistry(directory))


def _db_path(request: Request) -> str:
    registry = _registry(request)
    if registry is None:
        path = request.app.state.db_path or os.environ.get(ENV_DB_PATH)
        if not path:
            raise DatabaseNotConfigured()
        return path
    # Requests that carry no project of their own (steps, relations) send it as a header.
    project = request.query_params.get("project") or request.headers.get("X-Lineage-Project")
    if not project:
        raise ApiError(400, "INVALID_REQUEST", "Provide the project (project parameter or X-Lineage-Project header).")
    entry = registry.find(project)
    if entry is None:
        raise ApiError(404, "PROJECT_NOT_FOUND", f"Unknown project: {project}")
    if not entry["ready"]:
        raise ApiError(503, "PROJECT_NOT_READY", f"{project}: {entry['problem']}")
    return str(entry["path"])


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = open_readonly(_db_path(request))
    try:
        check_schema(conn)
        yield conn
    finally:
        conn.close()


def _require_project(conn: sqlite3.Connection, project: str) -> None:
    if project not in list_projects(conn):
        raise ApiError(404, "PROJECT_NOT_FOUND", f"Unknown project: {project}")


def _api_targets(
    conn: sqlite3.Connection, project: str, cache: TargetCatalogCache | None = None
) -> list[dict]:
    if not _has_target_components(conn):
        return list_target_objects(conn, project)
    return [
        {key: value for key, value in target.items() if not key.startswith("_")}
        for target in target_definitions(conn, project, cache)
    ]


def _api_columns(conn: sqlite3.Connection, project: str, object_id: str) -> list[dict]:
    if _has_target_components(conn):
        return list_target_component_columns(conn, project, object_id)
    return list_target_columns(conn, project, object_id)


def _require_object(
    conn: sqlite3.Connection, project: str, object_id: str, cache: TargetCatalogCache | None = None
) -> None:
    _require_project(conn, project)
    if not any(o["object_id"] == object_id for o in _api_targets(conn, project, cache)):
        raise ApiError(404, "TARGET_OBJECT_NOT_FOUND", f"Unknown target object: {object_id}")


def _require_column(
    conn: sqlite3.Connection, project: str, object_id: str, column_id: str,
    cache: TargetCatalogCache | None = None,
) -> None:
    _require_object(conn, project, object_id, cache)
    if not any(c["column_id"] == column_id for c in _api_columns(conn, project, object_id)):
        raise ApiError(404, "TARGET_COLUMN_NOT_FOUND", f"Unknown target column: {column_id}")


def create_app(db_path: Optional[str] = None, outputs_dir: Optional[str] = None, catalog_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="Data Lineage API", version="1.0.0")
    app.state.db_path = db_path
    app.state.outputs_dir = outputs_dir
    app.state.registries = {}
    app.state.source_cache = TargetSourceCache()
    app.state.summary_cache = TableSummaryCache()
    app.state.catalog_cache = TargetCatalogCache()
    app.state.business_catalog = BusinessCatalog(catalog_path)
    app.state.analysis_stats = AnalysisStatsCache()

    @app.exception_handler(ApiError)
    def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(StepNotFound)
    def _step_not_found(_: Request, exc: StepNotFound) -> JSONResponse:
        return _error(404, "STEP_NOT_FOUND", f"Unknown step: {exc}")

    @app.exception_handler(RelationNotFound)
    def _relation_not_found(_: Request, exc: RelationNotFound) -> JSONResponse:
        return _error(404, "RELATION_NOT_FOUND", f"Unknown relation: {exc}")

    @app.exception_handler(DatabaseNotConfigured)
    def _not_configured(_: Request, __: DatabaseNotConfigured) -> JSONResponse:
        return _error(503, "DATABASE_NOT_CONFIGURED", "No lineage database is configured.")

    @app.exception_handler(DatabaseUnavailable)
    def _unavailable(_: Request, __: DatabaseUnavailable) -> JSONResponse:
        return _error(503, "DATABASE_UNAVAILABLE", "The lineage database is unavailable.")

    @app.exception_handler(sqlite3.Error)
    def _sqlite_error(_: Request, __: sqlite3.Error) -> JSONResponse:
        return _error(503, "DATABASE_ERROR", "The lineage database could not be read.")

    @app.exception_handler(SchemaMismatch)
    def _schema_mismatch(_: Request, exc: SchemaMismatch) -> JSONResponse:
        return _error(503, "DATABASE_SCHEMA_MISMATCH", f"The lineage database schema is not supported: {exc}")

    @app.exception_handler(RequestValidationError)
    def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'] if p != 'query')}: {e['msg']}" for e in exc.errors()
        )
        return _error(422, "VALIDATION_ERROR", detail)

    @app.exception_handler(StarletteHTTPException)
    def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return _error(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail))

    @app.get("/projects", response_model=list[schemas.ProjectOut], response_model_exclude_none=True)
    def projects(request: Request):
        registry = _registry(request)
        if registry is not None:
            catalog = request.app.state.business_catalog.entries()
            reg_entries = registry.entries()
            out: list[dict] = []
            for e in reg_entries:
                row: dict = {
                    "project_name": e["project_name"], "folder": e["folder"],
                    **({} if e["ready"] else {"ready": False, "problem": e["problem"]}),
                    **({"application": e["application"]} if e.get("application") else {}),
                    **({} if e.get("startable", True) else {"startable": False}),
                }
                meta = catalog.get(e["project_name"])
                if meta is not None:
                    row.update(meta)
                    if e["ready"]:
                        missing = [t for t in meta["business_tables"] if t not in (e.get("known_tables") or [])]
                        if missing:
                            row["catalog_notes"] = [
                                f"Catalog table {t} was not found in {e['project_name']}." for t in missing
                            ]
                elif e["ready"] and catalog:
                    row["catalog_notes"] = [
                        f"{e['project_name']} has no catalog entry; it only shows in the developer view."
                    ]
                out.append(row)
            for name, meta in catalog.items():
                if not any(e["project_name"] == name for e in reg_entries):
                    out.append({"project_name": name, **meta, "ready": False, "startable": False,
                                "problem": "Listed in the catalog, but no database was found."})
            return sorted(out, key=lambda r: r["project_name"])
        conn = open_readonly(_db_path(request))
        try:
            check_schema(conn)
            return [{"project_name": p} for p in list_projects(conn)]
        finally:
            conn.close()

    @app.get("/catalog/analysis-stats", response_model=schemas.AnalysisStatsOut)
    def catalog_analysis_stats(request: Request, pair: list[str] = Query([])):
        """'What the tool analyzed' numbers behind the given `project:table` pairs."""
        registry = _registry(request)
        if registry is None:
            return {field: 0 for field in schemas.AnalysisStatsOut.model_fields}
        return request.app.state.analysis_stats.get(registry, pair)

    @app.get("/targets", response_model=list[schemas.TargetObjectOut])
    def targets(request: Request, project: str = Query(...), conn: sqlite3.Connection = Depends(get_conn)):
        _require_project(conn, project)
        return _api_targets(conn, project, request.app.state.catalog_cache)

    @app.get("/targets/search", response_model=list[schemas.TargetObjectOut])
    def search_targets(request: Request, project: str = Query(...), q: str = "", conn: sqlite3.Connection = Depends(get_conn)):
        _require_project(conn, project)
        if not _has_target_components(conn):
            return search_target_objects(conn, project, q)
        needle = q.strip().casefold()
        return [
            t for t in _api_targets(conn, project, request.app.state.catalog_cache)
            if not needle or needle in t["object_name"].casefold()
        ]

    def _summary_for(
        conn: sqlite3.Connection, project: str, object_id: str, cache: TargetCatalogCache | None = None
    ) -> tuple[dict, str]:
        """(summary, object name) as shown in the UI; shared by the JSON and Excel endpoints."""
        target = find_target(conn, project, object_id, cache) if _has_target_components(conn) else None
        if target is not None:
            summary = app.state.summary_cache.get_computed(
                conn,
                (project, object_id),
                lambda: summarize_target(conn, project, object_id, cache=cache),
            )
            return summary, target["object_name"]
        summary = app.state.summary_cache.get(conn, project, object_id)
        obj = next(o for o in _api_targets(conn, project, cache) if o["object_id"] == object_id)
        return summary, obj["object_name"]

    @app.get("/targets/{object_id}/summary", response_model=schemas.TableSummaryOut)
    def table_summary(request: Request, object_id: str, project: str = Query(...), conn: sqlite3.Connection = Depends(get_conn)):
        cache = request.app.state.catalog_cache
        _require_object(conn, project, object_id, cache)
        summary, _ = _summary_for(conn, project, object_id, cache)
        target = find_target(conn, project, object_id, cache) if _has_target_components(conn) else None
        if target is not None:
            public_target = {key: value for key, value in target.items() if not key.startswith("_")}
            return {**summary, "object": public_target}
        obj = next(o for o in _api_targets(conn, project, cache) if o["object_id"] == object_id)
        return {**summary, "object": obj}

    @app.get("/targets/{object_id}/export.xlsx")
    def table_summary_export(request: Request, object_id: str, project: str = Query(...), conn: sqlite3.Connection = Depends(get_conn)):
        cache = request.app.state.catalog_cache
        _require_object(conn, project, object_id, cache)
        summary, object_name = _summary_for(conn, project, object_id, cache)
        content = build_table_workbook(conn, project, object_name, summary)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{project}_{object_name}_lineage.xlsx"'},
        )

    @app.get("/targets/{object_id}/columns", response_model=list[schemas.TargetColumnOut])
    def target_columns(request: Request, object_id: str, project: str = Query(...), conn: sqlite3.Connection = Depends(get_conn)):
        _require_object(conn, project, object_id, request.app.state.catalog_cache)
        return _api_columns(conn, project, object_id)

    @app.get("/lineage/upstream", response_model=schemas.UpstreamOut)
    def upstream(
        request: Request,
        step_id: Optional[str] = None,
        project: Optional[str] = None,
        object_id: Optional[str] = None,
        column_id: Optional[str] = None,
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """Pass `step_id` for the choices below a step, or project/object_id/column_id for a target's."""
        if step_id is not None:
            return {"choices": get_upstream_choices(conn, step_id)}
        if project is None or object_id is None or column_id is None:
            raise ApiError(400, "INVALID_REQUEST", "Provide step_id, or project, object_id and column_id.")
        _require_column(conn, project, object_id, column_id, request.app.state.catalog_cache)
        pairs = target_column_pairs(conn, project, object_id, column_id, request.app.state.catalog_cache)
        if pairs:
            return {
                "choices": [
                    choice
                    for bp_id, root_id, root_column_id in pairs
                    for choice in get_root_choices(conn, project, root_id, root_column_id, bp_id)
                ]
            }
        return {"choices": get_root_choices(conn, project, object_id, column_id)}

    @app.get("/lineage/ultimate-sources", response_model=schemas.UltimateSourcesOut)
    def ultimate_sources(
        request: Request,
        project: str = Query(...),
        object_id: str = Query(...),
        column_id: str = Query(...),
        step_id: Optional[str] = None,
        session_id: str = Header("shared", alias="X-Session-Id", max_length=128),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        cache = request.app.state.catalog_cache
        _require_column(conn, project, object_id, column_id, cache)
        pairs = target_column_pairs(conn, project, object_id, column_id, cache)
        if pairs:
            if step_id:
                root = conn.execute(
                    "SELECT business_process_id,root_target_object_id,root_target_column_id FROM business_lineage_step WHERE step_id=?",
                    (step_id,),
                ).fetchone()
                matching = [p for p in pairs if (p[0], p[1], p[2]) == tuple(root)] if root else []
                if not matching:
                    raise StepNotFound(step_id)
                bp_id, root_id, root_column_id = matching[0]
                resolved = app.state.source_cache.get(
                    conn, session_id, project, root_id, root_column_id, bp_id
                )
                terminal_sources = sources_for_step(resolved, step_id)
            else:
                combined: dict[tuple, dict] = {}
                for bp_id, root_id, root_column_id in pairs:
                    resolved = app.state.source_cache.get(
                        conn, session_id, project, root_id, root_column_id, bp_id
                    )
                    for source in sources_for_step(resolved):
                        key = (source["terminal_id"], source["object_id"], source["column_id"],
                               source["condition"], source["result_expression"])
                        existing = combined.get(key)
                        if existing is None:
                            combined[key] = dict(source)
                        else:
                            existing["leaf_relation_types"] = sorted(
                                set(existing["leaf_relation_types"]) | set(source["leaf_relation_types"])
                            )
                terminal_sources = sorted(
                    combined.values(), key=lambda t: (t["object_name"], t["column_name"], t["terminal_id"])
                )
            return {
                "project": project,
                "object_id": object_id,
                "column_id": column_id,
                "step_id": step_id,
                "terminal_sources": terminal_sources,
            }
        resolved = app.state.source_cache.get(conn, session_id, project, object_id, column_id)
        return {
            "project": project,
            "object_id": object_id,
            "column_id": column_id,
            "step_id": step_id,
            "terminal_sources": sources_for_step(resolved, step_id),
        }

    @app.get("/lineage/graph", response_model=schemas.ColumnGraphOut)
    def column_graph(
        request: Request,
        project: str = Query(...),
        object_id: str = Query(...),
        column_id: str = Query(...),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        cache = request.app.state.catalog_cache
        _require_column(conn, project, object_id, column_id, cache)
        if _has_target_components(conn) and target_column_pairs(conn, project, object_id, column_id, cache):
            return build_target_graph(conn, project, object_id, column_id)
        return build_column_graph(conn, project, object_id, column_id)

    @app.get("/lineage/continuations", response_model=list[schemas.ContinuationOut])
    def continuations(
        request: Request,
        project: str = Query(...),
        object_name: str = Query(...),
        column_name: str = Query(...),
    ):
        registry = _registry(request)
        if registry is None:
            return []
        return find_continuations(
            registry, project, object_name, column_name, cache=request.app.state.catalog_cache
        )

    @app.get("/lineage/remaining-depth", response_model=schemas.RemainingDepthOut)
    def remaining_depth(step_id: str = Query(...), conn: sqlite3.Connection = Depends(get_conn)):
        return get_remaining_depth(conn, step_id)

    @app.get("/steps/{step_id}", response_model=schemas.StepDetailOut)
    def step_detail(step_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return get_step_detail(conn, step_id)

    @app.get("/relations/{relation_id}", response_model=schemas.RelationDetailOut)
    def relation_detail(relation_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return get_relation_detail(conn, relation_id)

    return app


app = create_app()
