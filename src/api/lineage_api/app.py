"""Read-only lineage API: the boundary between the browser and the SQLite lineage DB."""
import os
import sqlite3
from typing import Iterator, Optional

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from lineage_api import schemas
from lineage_api.catalog import list_projects, list_target_columns, list_target_objects
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
from lineage_api.sources import TargetSourceCache, sources_for_step
from lineage_api.upstream import StepNotFound, get_root_choices, get_upstream_choices


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    path = request.app.state.db_path or os.environ.get(ENV_DB_PATH)
    if not path:
        raise DatabaseNotConfigured()
    conn = open_readonly(path)
    try:
        check_schema(conn)
        yield conn
    finally:
        conn.close()


def _require_project(conn: sqlite3.Connection, project: str) -> None:
    if project not in list_projects(conn):
        raise ApiError(404, "PROJECT_NOT_FOUND", f"Unknown project: {project}")


def _require_object(conn: sqlite3.Connection, project: str, object_id: str) -> None:
    _require_project(conn, project)
    if not any(o["object_id"] == object_id for o in list_target_objects(conn, project)):
        raise ApiError(404, "TARGET_OBJECT_NOT_FOUND", f"Unknown target object: {object_id}")


def _require_column(conn: sqlite3.Connection, project: str, object_id: str, column_id: str) -> None:
    _require_object(conn, project, object_id)
    if not any(c["column_id"] == column_id for c in list_target_columns(conn, project, object_id)):
        raise ApiError(404, "TARGET_COLUMN_NOT_FOUND", f"Unknown target column: {column_id}")


def create_app(db_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="Data Lineage API", version="1.0.0")
    app.state.db_path = db_path
    app.state.source_cache = TargetSourceCache()

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

    @app.get("/projects", response_model=list[schemas.ProjectOut])
    def projects(conn: sqlite3.Connection = Depends(get_conn)):
        return [{"project_name": p} for p in list_projects(conn)]

    @app.get("/targets", response_model=list[schemas.TargetObjectOut])
    def targets(project: str = Query(...), conn: sqlite3.Connection = Depends(get_conn)):
        _require_project(conn, project)
        return list_target_objects(conn, project)

    @app.get("/targets/{object_id}/columns", response_model=list[schemas.TargetColumnOut])
    def target_columns(object_id: str, project: str = Query(...), conn: sqlite3.Connection = Depends(get_conn)):
        _require_object(conn, project, object_id)
        return list_target_columns(conn, project, object_id)

    @app.get("/lineage/upstream", response_model=schemas.UpstreamOut)
    def upstream(
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
        _require_column(conn, project, object_id, column_id)
        return {"choices": get_root_choices(conn, project, object_id, column_id)}

    @app.get("/lineage/ultimate-sources", response_model=schemas.UltimateSourcesOut)
    def ultimate_sources(
        project: str = Query(...),
        object_id: str = Query(...),
        column_id: str = Query(...),
        step_id: Optional[str] = None,
        session_id: str = Header("shared", alias="X-Session-Id", max_length=128),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        _require_column(conn, project, object_id, column_id)
        resolved = app.state.source_cache.get(conn, session_id, project, object_id, column_id)
        return {
            "project": project,
            "object_id": object_id,
            "column_id": column_id,
            "step_id": step_id,
            "terminal_sources": sources_for_step(resolved, step_id),
        }

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
