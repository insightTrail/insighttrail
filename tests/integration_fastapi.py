import json
import time
import threading
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from typing import Optional

from insighttrail import FastAPIInsightTrail
from insighttrail.logger import shutdown_logger, logger


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    priority: int = 0


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None


TASKS_DB = {}
TASK_COUNTER = 0


def _reset_db():
    global TASKS_DB, TASK_COUNTER
    TASKS_DB = {}
    TASK_COUNTER = 0


def _seed_tasks():
    global TASKS_DB, TASK_COUNTER
    _reset_db()
    for i, (title, desc, pri) in enumerate([
        ("Fix login bug", "Auth fails on mobile", 2),
        ("Write docs", "API reference", 1),
        ("Deploy v2", "Release pipeline", 3),
    ], start=1):
        TASKS_DB[i] = {"id": i, "title": title, "description": desc, "priority": pri, "done": False}
    TASK_COUNTER = 3


@pytest.fixture
def realistic_app(tmp_log_dir):
    _reset_db()
    app = FastAPI(title="TaskManager")

    @app.get("/tasks")
    def list_tasks():
        return list(TASKS_DB.values())

    @app.get("/tasks/{task_id}")
    def get_task(task_id: int):
        if task_id not in TASKS_DB:
            raise HTTPException(status_code=404, detail="Task not found")
        return TASKS_DB[task_id]

    @app.post("/tasks", status_code=201)
    def create_task(task: TaskCreate):
        global TASK_COUNTER
        TASK_COUNTER += 1
        new_task = {"id": TASK_COUNTER, "title": task.title, "description": task.description, "priority": task.priority, "done": False}
        TASKS_DB[TASK_COUNTER] = new_task
        return new_task

    @app.put("/tasks/{task_id}")
    def update_task(task_id: int, task: TaskUpdate):
        if task_id not in TASKS_DB:
            raise HTTPException(status_code=404, detail="Task not found")
        stored = TASKS_DB[task_id]
        if task.title is not None:
            stored["title"] = task.title
        if task.description is not None:
            stored["description"] = task.description
        if task.priority is not None:
            stored["priority"] = task.priority
        return stored

    @app.delete("/tasks/{task_id}", status_code=204)
    def delete_task(task_id: int):
        if task_id not in TASKS_DB:
            raise HTTPException(status_code=404, detail="Task not found")
        del TASKS_DB[task_id]

    @app.get("/tasks/search")
    def search_tasks(q: str = ""):
        results = [t for t in TASKS_DB.values() if q.lower() in t["title"].lower()]
        return results

    @app.get("/error")
    def trigger_error():
        raise ValueError("Intentional integration test error")

    @app.get("/auth")
    def auth_check(authorization: str = Header(None)):
        if authorization != "Bearer test-token":
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"authenticated": True}

    @app.get("/slow")
    def slow_endpoint():
        time.sleep(0.05)
        return {"status": "slow"}

    app.insighttrail_middleware = FastAPIInsightTrail(
        app,
        log_file=str(tmp_log_dir / "integration.log"),
        log_level="DEBUG",
        enable_ui=True,
        url_prefix="/insight",
        track_internal_requests=False,
        async_logging=False,
        dependency_check=False,
        enable_excel_reports=True,
        capture_runtime=True,
        capture_system_metrics=False,
    )
    return app


@pytest.fixture
def client(realistic_app):
    return TestClient(realistic_app, raise_server_exceptions=False)


def _read_logs(log_file):
    entries = []
    try:
        with open(log_file, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except FileNotFoundError:
        pass
    return entries


@pytest.fixture(autouse=True)
def _seed():
    _seed_tasks()
    yield
    _reset_db()


class TestRequestLogging:
    def test_all_requests_logged(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        routes = [
            ("GET", "/tasks"),
            ("GET", "/tasks/1"),
            ("POST", "/tasks", {"title": "New", "description": "desc"}),
            ("PUT", "/tasks/1", {"title": "Updated"}),
            ("DELETE", "/tasks/2"),
            ("GET", "/tasks/search?q=fix"),
            ("GET", "/error"),
            ("GET", "/auth", None, {"Authorization": "Bearer test-token"}),
            ("GET", "/auth"),
            ("GET", "/slow"),
        ]
        for spec in routes:
            method, path = spec[0], spec[1]
            body = spec[2] if len(spec) > 2 and isinstance(spec[2], dict) else None
            headers = spec[3] if len(spec) > 3 else None
            kwargs = {}
            if body:
                kwargs["json"] = body
            if headers:
                kwargs["headers"] = headers
            client.request(method, path, **kwargs)

        logs = _read_logs(log_file)
        logged_paths = [l["request"]["path"] for l in logs]
        assert "/tasks" in logged_paths
        assert "/error" in logged_paths
        assert len(logs) >= len(routes)

    def test_trace_id_unique_per_request(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        client.get("/tasks")
        client.get("/tasks/1")
        client.get("/error")

        logs = _read_logs(log_file)
        trace_ids = [l["trace_id"] for l in logs]
        assert len(trace_ids) == len(set(trace_ids))

    def test_request_method_captured(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        client.get("/tasks")
        client.post("/tasks", json={"title": "X"})
        client.put("/tasks/1", json={"title": "Y"})
        client.delete("/tasks/3")

        logs = _read_logs(log_file)
        methods = [l["request"]["method"] for l in logs]
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods

    def test_duration_positive(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        client.get("/tasks")
        client.get("/slow")

        logs = _read_logs(log_file)
        for entry in logs:
            assert entry["request"]["duration_ms"] >= 0

    def test_client_ip_captured(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        client.get("/tasks")

        logs = _read_logs(log_file)
        assert len(logs) >= 1
        assert logs[-1]["request"]["client"] is not None


class TestErrorCapture:
    def test_error_captures_traceback(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        resp = client.get("/error")
        assert resp.status_code == 500

        logs = _read_logs(log_file)
        error_logs = [l for l in logs if l.get("error")]
        assert len(error_logs) >= 1
        last_error = error_logs[-1]
        assert last_error["error"]["type"] == "ValueError"
        assert last_error["error"]["message"] == "Intentional integration test error"
        assert last_error["error"]["traceback"] is not None
        assert "trigger_error" in last_error["error"]["traceback"]

    def test_error_status_logged(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        client.get("/error")
        client.get("/tasks/9999")
        client.get("/auth")

        logs = _read_logs(log_file)
        statuses = [l["request"]["status"] for l in logs]
        assert 500 in statuses
        assert 404 in statuses
        assert 401 in statuses


class TestSampling:
    def test_success_not_sampled_out(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        for _ in range(5):
            client.get("/tasks")

        logs = _read_logs(log_file)
        assert len(logs) >= 5

    def test_sample_rate_filtering(self, tmp_log_dir):
        app = FastAPI()

        @app.get("/ok")
        def ok():
            return {"ok": True}

        @app.get("/err")
        def err():
            raise ValueError("fail")

        FastAPIInsightTrail(
            app,
            log_file=str(tmp_log_dir / "sample.log"),
            log_level="DEBUG",
            enable_ui=False,
            async_logging=False,
            dependency_check=False,
            success_log_sample_rate=0.0,
        )
        c = TestClient(app, raise_server_exceptions=False)
        for _ in range(20):
            c.get("/ok")
        c.get("/err")

        logs = _read_logs(str(tmp_log_dir / "sample.log"))
        error_logs = [l for l in logs if l.get("error")]
        success_logs = [l for l in logs if not l.get("error") and l["level"] == "INFO"]
        assert len(error_logs) >= 1
        assert len(success_logs) == 0


class TestDashboard:
    def test_dashboard_renders(self, client):
        resp = client.get("/insight/")
        assert resp.status_code == 200
        assert "InsightTrail" in resp.text

    def test_dashboard_logs_api(self, client):
        resp = client.get("/insight/api/analytics/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert "metrics" in data
        assert "logger" in data

    def test_search_by_trace_id(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        client.get("/tasks")
        logs = _read_logs(log_file)
        assert len(logs) >= 1
        trace_id = logs[0]["trace_id"]

        resp = client.get(f"/insight/api/analytics/search?trace_id={trace_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert any(l["trace_id"] == trace_id for l in data["logs"])

    def test_excel_export(self, client, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        client.get("/tasks")
        client.get("/error")

        resp = client.get("/insight/api/reports/excel?preset=1d&include=summary,requests,errors")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]


class TestInternalRequests:
    def test_internal_requests_excluded(self, tmp_log_dir):
        app = FastAPI()

        @app.get("/ok")
        def ok():
            return {"ok": True}

        FastAPIInsightTrail(
            app,
            log_file=str(tmp_log_dir / "internal.log"),
            log_level="DEBUG",
            enable_ui=True,
            url_prefix="/insight",
            track_internal_requests=False,
            async_logging=False,
            dependency_check=False,
        )
        c = TestClient(app, raise_server_exceptions=False)
        c.get("/ok")
        c.get("/insight/")
        c.get("/insight/api/analytics/logs")

        logs = _read_logs(str(tmp_log_dir / "internal.log"))
        insight_paths = [l["request"]["path"] for l in logs if l["request"]["path"].startswith("/insight")]
        assert len(insight_paths) == 0

    def test_internal_requests_included(self, tmp_log_dir):
        app = FastAPI()

        @app.get("/ok")
        def ok():
            return {"ok": True}

        FastAPIInsightTrail(
            app,
            log_file=str(tmp_log_dir / "internal_inc.log"),
            log_level="DEBUG",
            enable_ui=True,
            url_prefix="/insight",
            track_internal_requests=True,
            async_logging=False,
            dependency_check=False,
        )
        c = TestClient(app, raise_server_exceptions=False)
        c.get("/ok")
        c.get("/insight/")
        c.get("/insight/api/analytics/logs")

        logs = _read_logs(str(tmp_log_dir / "internal_inc.log"))
        insight_paths = [l["request"]["path"] for l in logs if l["request"]["path"].startswith("/insight")]
        assert len(insight_paths) >= 2


class TestConcurrency:
    def test_concurrent_requests(self, realistic_app):
        log_file = realistic_app.insighttrail_middleware.log_file
        c = TestClient(realistic_app, raise_server_exceptions=False)
        errors = []

        def make_request(i):
            try:
                resp = c.get("/tasks")
                assert resp.status_code == 200
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=make_request, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        logs = _read_logs(log_file)
        assert len(logs) >= 20
        trace_ids = [l["trace_id"] for l in logs]
        assert len(trace_ids) == len(set(trace_ids))
