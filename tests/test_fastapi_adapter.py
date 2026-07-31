import json
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
from insighttrail import FastAPIInsightTrail


class TestFastAPIInit:
    def test_init_defaults(self, fastapi_app):
        mw = fastapi_app.insighttrail_middleware
        assert mw.url_prefix == "/insight"
        assert mw.capture_runtime is False
        assert mw.capture_system_metrics is False
        assert mw.enable_excel_reports is True
        assert mw.success_log_sample_rate == 1.0
        assert mw.track_internal_requests is False

    def test_ultra_light_mode_disables_features(self, tmp_path):
        log_file = str(tmp_path / "logs" / "test.log")
        app = FastAPI()
        mw = FastAPIInsightTrail(
            app,
            log_file=log_file,
            ultra_light_mode=True,
            enable_ui=False,
            async_logging=False,
        )
        assert mw.dependency_check is False
        assert mw.enable_charts is False


class TestFastAPIRequestLogging:
    def test_successful_request_logged(self, fastapi_client, fastapi_app):
        fastapi_client.get("/")
        with open(fastapi_app.insighttrail_middleware.log_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["request"]["path"] == "/"
        assert entry["request"]["status"] == 200

    def test_error_request_logged(self, fastapi_client, fastapi_app):
        fastapi_client.get("/error")
        with open(fastapi_app.insighttrail_middleware.log_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        error_entries = [json.loads(l) for l in lines if json.loads(l).get("error")]
        assert len(error_entries) >= 1
        assert error_entries[0]["error"]["type"] == "ValueError"

    def test_internal_requests_excluded(self, fastapi_client, fastapi_app):
        fastapi_client.get("/")
        fastapi_client.get("/insight/api/packages")
        with open(fastapi_app.insighttrail_middleware.log_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        paths = [json.loads(l)["request"]["path"] for l in lines]
        assert "/" in paths
        assert "/insight/api/packages" not in paths

    def test_slow_request_threshold(self, tmp_path):
        log_file = str(tmp_path / "logs" / "slow.log")
        app = FastAPI()

        @app.get("/slow")
        def slow():
            import time
            time.sleep(0.1)
            return {"status": "slow"}

        FastAPIInsightTrail(
            app,
            log_file=log_file,
            slow_request_threshold_ms=50,
            success_log_sample_rate=0.0,
            enable_ui=False,
            async_logging=False,
        )
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/slow")
        with open(log_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        slow_entries = [
            json.loads(l) for l in lines
            if json.loads(l)["request"]["path"] == "/slow"
        ]
        assert len(slow_entries) >= 1


class TestFastAPIDashboard:
    def test_monochrome_theme_is_rendered(self, tmp_path):
        app = FastAPI()
        FastAPIInsightTrail(
            app,
            log_file=str(tmp_path / 'theme.log'),
            enable_ui=True,
            color_scheme='monochrome',
            async_logging=False,
            dependency_check=False,
        )
        response = TestClient(app).get('/insight/')
        assert response.status_code == 200
        assert 'data-scheme="monochrome"' in response.text
        assert 'function escapeHtml' in response.text

    def test_dashboard_renders(self, fastapi_client):
        resp = fastapi_client.get("/insight/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()
        assert resp.headers['x-content-type-options'] == 'nosniff'
        assert resp.headers['x-frame-options'] == 'DENY'

    def test_api_packages_returns_list(self, fastapi_client):
        resp = fastapi_client.get("/insight/api/packages")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_api_analytics_returns_data(self, fastapi_client):
        fastapi_client.get("/")
        resp = fastapi_client.get("/insight/api/analytics/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert "metrics" in data
        assert "logger" in data


class TestFastAPIExcelReports:
    def test_excel_report_generates(self, fastapi_client):
        fastapi_client.get("/")
        resp = fastapi_client.get("/insight/api/reports/excel?preset=1d")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers.get("content-type", "")

    def test_excel_report_disabled(self, tmp_path):
        log_file = str(tmp_path / "logs" / "disabled.log")
        app = FastAPI()
        FastAPIInsightTrail(
            app,
            log_file=log_file,
            enable_excel_reports=False,
            enable_ui=True,
            async_logging=False,
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/insight/api/reports/excel?preset=1d")
        assert resp.status_code == 403
