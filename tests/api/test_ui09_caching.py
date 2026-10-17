import os
import shutil
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT

sys.path.insert(0, str(ROOT / "api"))

from lineage_api.app import create_app  # noqa: E402
from lineage_api.db import open_readonly  # noqa: E402
from lineage_api.migrations import add_business_process_columns  # noqa: E402
from lineage_api.sources import TargetSourceCache, resolve_terminal_sources, sources_for_step  # noqa: E402


@pytest.fixture()
def db_file(lineage_db_path, tmp_path):
    target = tmp_path / "lineage.db"
    shutil.copy(lineage_db_path, target)
    c = sqlite3.connect(target)
    add_business_process_columns(c)
    c.close()
    return target


@pytest.fixture()
def client(db_file, lineage_db_path):
    if lineage_db_path.parent.name != "SP_CLO":
        pytest.skip("SP_CLO-specific expectations")
    return TestClient(create_app(str(db_file)))


def _target(client, object_name, column_name):
    objects = client.get("/targets", params={"project": "SP_CLO"}).json()
    obj = next(o for o in objects if o["object_name"] == object_name and o["source_project"] == "SP_CLO")
    cols = client.get(f"/targets/{obj['object_id']}/columns", params={"project": "SP_CLO"}).json()
    col = next(c for c in cols if c["column_name"] == column_name)
    return {"project": "SP_CLO", "object_id": obj["object_id"], "column_id": col["column_id"]}


def _sources(client, target, session="s1", **extra):
    r = client.get("/lineage/ultimate-sources", params={**target, **extra}, headers={"X-Session-Id": session})
    assert r.status_code == 200
    return r.json()


def _cache(client):
    return client.app.state.source_cache


# --- repeated branch operations -----------------------------------------------------------------

def test_branch_navigation_on_one_target_computes_once(client):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    roots = client.get("/lineage/upstream", params=t).json()["choices"]
    _sources(client, t)
    for choice in roots:
        _sources(client, t, step_id=choice["step_id"])
    chain = next(c for c in roots if c["upstream_choice_count"] == 1)
    for child in client.get("/lineage/upstream", params={"step_id": chain["step_id"]}).json()["choices"]:
        _sources(client, t, step_id=child["step_id"])
    assert _cache(client).compute_count == 1


def test_cached_answers_equal_uncached_answers(client, db_file):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    roots = client.get("/lineage/upstream", params=t).json()["choices"]
    conn = open_readonly(db_file)
    fresh = resolve_terminal_sources(conn, t["project"], t["object_id"], t["column_id"])
    for step in [None] + [c["step_id"] for c in roots]:
        extra = {} if step is None else {"step_id": step}
        for _ in range(3):
            assert _sources(client, t, **extra)["terminal_sources"] == sources_for_step(fresh, step)
    conn.close()


def test_other_endpoints_do_not_touch_the_cache(client):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    client.get("/projects")
    client.get("/targets", params={"project": "SP_CLO"})
    step = client.get("/lineage/upstream", params=t).json()["choices"][0]["step_id"]
    client.get(f"/steps/{step}")
    client.get("/lineage/remaining-depth", params={"step_id": step})
    assert _cache(client).compute_count == 0


def test_rejected_requests_do_not_compute(client):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    client.get("/lineage/ultimate-sources", params={**t, "column_id": "COL_nope"})
    client.get("/lineage/ultimate-sources", params={**t, "project": "NOPE"})
    assert _cache(client).compute_count == 0


# --- replacement and invalidation ---------------------------------------------------------------

def test_changing_target_replaces_the_cached_target(client):
    a = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    b = _target(client, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    _sources(client, a)
    _sources(client, b)
    assert _cache(client).compute_count == 2
    _sources(client, b)
    assert _cache(client).compute_count == 2
    _sources(client, a)
    assert _cache(client).compute_count == 3


def test_sessions_are_independent(client):
    a = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    b = _target(client, "AR_PAR_LOAN_EVENTS", "MDE_CODE")
    _sources(client, a, session="one")
    _sources(client, b, session="two")
    _sources(client, a, session="one")
    _sources(client, b, session="two")
    assert _cache(client).compute_count == 2


def test_requests_without_session_header_share_one_entry(client):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    client.get("/lineage/ultimate-sources", params=t)
    client.get("/lineage/ultimate-sources", params=t)
    assert _cache(client).compute_count == 1


def test_oversized_session_id_is_rejected(client):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    r = client.get("/lineage/ultimate-sources", params=t, headers={"X-Session-Id": "x" * 200})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_changed_database_file_is_recomputed_and_not_stale(client, db_file):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    before = _sources(client, t)["terminal_sources"]
    assert len(before) == 4

    roots = client.get("/lineage/upstream", params=t).json()["choices"]
    chain = next(c for c in roots if c["upstream_choice_count"] == 1)
    rw = sqlite3.connect(db_file)
    rw.execute("UPDATE business_lineage_step SET is_terminal = 1 WHERE step_id = ?", (chain["step_id"],))
    rw.commit()
    rw.close()

    after = _sources(client, t)["terminal_sources"]
    assert _cache(client).compute_count == 2
    assert [s["column_name"] for s in after] == ["e_fdk_mt"]


def test_touched_database_file_invalidates_without_content_change(client, db_file):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    _sources(client, t)
    st = os.stat(db_file)
    os.utime(db_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    again = _sources(client, t)
    assert _cache(client).compute_count == 2
    assert len(again["terminal_sources"]) == 4


def test_replacing_the_database_file_invalidates(client, db_file, tmp_path):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    _sources(client, t)
    replacement = tmp_path / "regenerated.db"
    shutil.copy(db_file, replacement)
    os.replace(replacement, db_file)
    os.utime(db_file, ns=(os.stat(db_file).st_atime_ns, os.stat(db_file).st_mtime_ns + 2_000_000_000))
    _sources(client, t)
    assert _cache(client).compute_count == 2


# --- cache unit behaviour on the real DB ------------------------------------------------------

def test_cache_is_bounded_by_session_count(client, db_file):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    conn = open_readonly(db_file)
    cache = TargetSourceCache(max_sessions=2)
    for session in ("a", "b", "c"):
        cache.get(conn, session, t["project"], t["object_id"], t["column_id"])
    assert cache.compute_count == 3
    cache.get(conn, "c", t["project"], t["object_id"], t["column_id"])
    cache.get(conn, "b", t["project"], t["object_id"], t["column_id"])
    assert cache.compute_count == 3
    cache.get(conn, "a", t["project"], t["object_id"], t["column_id"])
    assert cache.compute_count == 4
    conn.close()


def test_concurrent_requests_for_one_target_compute_once(client):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _sources(client, t, session="burst"), range(32)))
    assert all(r == results[0] for r in results)
    assert _cache(client).compute_count == 1


def test_cache_clear(client, db_file):
    t = _target(client, "CM_PAR_LOAN_TRADES", "FDK_MT")
    _sources(client, t)
    _cache(client).clear()
    _sources(client, t)
    assert _cache(client).compute_count == 2
