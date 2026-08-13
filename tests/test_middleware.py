import json
import time
from flask import Flask
from insighttrail import FlaskInsightTrail


class TestMiddlewareInit:
    def test_init_defaults(self, flask_app):
        mw = flask_app.insighttrail_middleware
        assert mw.url_prefix == "/insight"
        assert mw.capture_runtime is False
        assert mw.capture_system_metrics is False
        assert mw.enable_excel_reports is True
        assert mw.success_log_sample_rate == 1.0
        assert mw.track_internal_requests is False

    def test_url_prefix_normalization(self, tmp_path):
        log_file = str(tmp_path / "logs" / "test.log")
        for prefix in ["insight", "/insight", "/insight/"]:
            app = Flask(__name__)
            mw = FlaskInsightTrail(
                app,
                log_file=log_file,
                url_prefix=prefix,
                enable_ui=False,
                async_logging=False,
            )
            assert mw.url_prefix == "/insight"

    def test_custom_url_prefix(self, tmp_path):
        log_file = str(tmp_path / "logs" / "test.log")
        app = Flask(__name__)
        mw = FlaskInsightTrail(
            app,
            log_file=log_file,
            url_prefix="/observability",
            enable_ui=False,
            async_logging=False,
        )
        assert mw.url_prefix == "/observability"

    def test_ultra_light_mode_disables_features(self, tmp_path):
        log_file = str(tmp_path / "logs" / "test.log")
        app = Flask(__name__)
        mw = FlaskInsightTrail(
            app,
            log_file=log_file,
            ultra_light_mode=True,
            enable_ui=False,
            async_logging=False,
        )
        assert mw.dependency_check is False
        assert mw.enable_charts is False

    def test_slow_request_threshold(self, tmp_path):
        log_file = str(tmp_path / "logs" / "test.log")
        app = Flask(__name__)
        mw = FlaskInsightTrail(
            app,
            log_file=log_file,
            slow_request_threshold_ms=500,
            enable_ui=False,
            async_logging=False,
        )
        assert mw.slow_request_threshold_ms == 500.0


class TestRequestLogging:
    def test_successful_request_logged(self, flask_client, flask_app):
        flask_client.get("/")
        time.sleep(0.1)
        with open(flask_app.insighttrail_middleware.log_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["request"]["path"] == "/"
        assert entry["request"]["status"] == 200

    def test_error_request_logged(self, flask_client, flask_app):
        flask_client.get("/error")
        time.sleep(0.1)
        with open(flask_app.insighttrail_middleware.log_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        error_entries = [json.loads(l) for l in lines if json.loads(l).get("error")]
        assert len(error_entries) >= 1
        assert error_entries[0]["error"]["type"] == "ValueError"

    def test_trace_id_present_in_log(self, flask_client, flask_app):
        flask_client.get("/")
        time.sleep(0.1)
        with open(flask_app.insighttrail_middleware.log_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        entry = json.loads(lines[0])
        assert "trace_id" in entry
        assert entry["trace_id"] is not None

    def test_internal_requests_excluded(self, flask_client, flask_app):
        flask_client.get("/")
        flask_client.get("/insight/api/packages")
        time.sleep(0.1)
        with open(flask_app.insighttrail_middleware.log_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        paths = [json.loads(l)["request"]["path"] for l in lines]
        assert "/" in paths
        assert "/insight/api/packages" not in paths

    def test_slow_request_always_logged(self, tmp_path):
        log_file = str(tmp_path / "logs" / "slow.log")
        app = Flask(__name__)

        @app.route("/slow")
        def slow():
            import time
            time.sleep(0.1)
            return {"status": "slow"}

        mw = FlaskInsightTrail(
            app,
            log_file=log_file,
            slow_request_threshold_ms=50,
            success_log_sample_rate=0.0,
            enable_ui=False,
            async_logging=False,
        )
        client = app.test_client()
        client.get("/slow")
        time.sleep(0.1)
        with open(mw.log_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        slow_entries = [
            json.loads(l) for l in lines
            if json.loads(l)["request"]["path"] == "/slow"
        ]
        assert len(slow_entries) >= 1

    def test_sample_rate_filters_success(self, tmp_path):
        log_file = str(tmp_path / "logs" / "sample.log")
        app = Flask(__name__)

        @app.route("/")
        def home():
            return {"message": "Hello"}

        mw = FlaskInsightTrail(
            app,
            log_file=log_file,
            success_log_sample_rate=0.0,
            enable_ui=False,
            async_logging=False,
        )
        client = app.test_client()
        client.get("/")
        time.sleep(0.1)
        with open(mw.log_file) as f:
            content = f.read()
        assert content.strip() == ""


class TestDashboardUI:
    def test_dashboard_renders(self, flask_client):
        resp = flask_client.get("/insight/")
        assert resp.status_code == 200
        assert b"<!DOCTYPE html>" in resp.data or b"<html" in resp.data

    def test_api_packages_returns_list(self, flask_client):
        resp = flask_client.get("/insight/api/packages")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_api_analytics_returns_metrics(self, flask_client):
        flask_client.get("/")
        time.sleep(0.1)
        resp = flask_client.get("/insight/api/analytics/logs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "logs" in data
        assert "metrics" in data
        assert "logger" in data
        assert "queue_depth" in data["logger"]

    def test_api_logs_pagination(self, flask_client):
        resp = flask_client.get("/insight/api/logs?limit=5")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "logs" in data
        assert "cursor" in data
        assert "has_more" in data

class TestExcelReports:
    def test_excel_report_generates(self, flask_client):
        flask_client.get("/")
        time.sleep(0.1)
        resp = flask_client.get("/insight/api/reports/excel?preset=1d")
        assert resp.status_code == 200
        assert resp.content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def test_excel_report_disabled(self, tmp_path):
        log_file = str(tmp_path / "logs" / "disabled.log")
        app = Flask(__name__)
        FlaskInsightTrail(
            app,
            log_file=log_file,
            enable_excel_reports=False,
            enable_ui=True,
            async_logging=False,
        )
        client = app.test_client()
        resp = client.get("/insight/api/reports/excel?preset=1d")
        assert resp.status_code == 403

    def test_excel_report_estimate(self, flask_client):
        resp = flask_client.get("/insight/api/reports/estimate?preset=1d")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "estimated_rows" in data
        assert "report_max_rows" in data
