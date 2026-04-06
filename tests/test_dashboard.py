"""
Test delle route del dashboard.
"""
from __future__ import annotations


class TestDashboardRoutes:
    """Smoke test: tutte le pagine rispondono 200."""

    def test_home(self, test_client):
        r = test_client.get("/")
        assert r.status_code == 200

    def test_analytics(self, test_client):
        r = test_client.get("/analytics")
        assert r.status_code == 200

    def test_context(self, test_client):
        r = test_client.get("/context")
        assert r.status_code == 200

    def test_competitors(self, test_client):
        r = test_client.get("/competitors")
        assert r.status_code == 200

    def test_competitor_analysis(self, test_client):
        r = test_client.get("/competitors/analysis")
        assert r.status_code == 200

    def test_settings(self, test_client):
        r = test_client.get("/settings")
        assert r.status_code == 200


class TestURLValidation:
    """Test della funzione _is_safe_url."""

    def test_valid_https(self):
        from dashboard.main import _is_safe_url
        assert _is_safe_url("https://example.com") is True

    def test_valid_http(self):
        from dashboard.main import _is_safe_url
        assert _is_safe_url("http://example.com/page") is True

    def test_file_scheme_blocked(self):
        from dashboard.main import _is_safe_url
        assert _is_safe_url("file:///etc/passwd") is False

    def test_localhost_blocked(self):
        from dashboard.main import _is_safe_url
        assert _is_safe_url("http://localhost:8080") is False

    def test_loopback_blocked(self):
        from dashboard.main import _is_safe_url
        assert _is_safe_url("http://127.0.0.1:3000") is False

    def test_link_local_blocked(self):
        from dashboard.main import _is_safe_url
        assert _is_safe_url("http://169.254.169.254") is False

    def test_private_blocked(self):
        from dashboard.main import _is_safe_url
        assert _is_safe_url("http://192.168.1.1") is False
        assert _is_safe_url("http://10.0.0.1") is False

    def test_empty_blocked(self):
        from dashboard.main import _is_safe_url
        assert _is_safe_url("") is False

    def test_javascript_blocked(self):
        from dashboard.main import _is_safe_url
        assert _is_safe_url("javascript:alert(1)") is False


class TestSanitization:
    """Test della sanitizzazione valori .env."""

    def test_removes_newlines(self):
        from dashboard.main import _sanitize_env_value
        assert _sanitize_env_value("hello\nworld") == "helloworld"

    def test_removes_carriage_return(self):
        from dashboard.main import _sanitize_env_value
        assert _sanitize_env_value("hello\r\nworld") == "helloworld"

    def test_removes_null_bytes(self):
        from dashboard.main import _sanitize_env_value
        assert _sanitize_env_value("hello\0world") == "helloworld"

    def test_normal_value_unchanged(self):
        from dashboard.main import _sanitize_env_value
        assert _sanitize_env_value("http://example.com") == "http://example.com"
