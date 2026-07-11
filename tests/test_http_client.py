"""HttpClient 单元测试。"""

from unittest.mock import MagicMock, patch

from src.core.cookie_store import CookieStore
from src.http.client import HttpClient


class TestHttpClient:
    def test_init_defaults(self):
        client = HttpClient()
        assert client.base_timeout == 30
        assert client.max_redirects == 10

    def test_init_custom(self):
        client = HttpClient(base_timeout=5, max_redirects=2)
        assert client.base_timeout == 5
        assert client.max_redirects == 2

    def test_fetch_injects_cookies(self):
        store = CookieStore()
        store.store("example.com", [
            {"name": "session", "value": "abc123"},
            {"name": "token", "value": "xyz789"},
        ])

        mock_response = MagicMock()
        mock_response.url = "https://example.com/api"
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"ok": true}'

        client = HttpClient(base_timeout=10)
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response
            result = client.fetch("https://example.com/api", cookie_store=store)
            assert result["status_code"] == 200
            assert result["cookies_used"] == ["session", "token"]
            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            headers = call_args[1]["headers"]
            assert "Cookie" in headers
            assert "session=abc123" in headers["Cookie"]

    def test_fetch_without_cookie_store(self):
        mock_response = MagicMock()
        mock_response.url = "https://example.com/api"
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.text = "ok"

        client = HttpClient(base_timeout=10)
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response
            result = client.fetch("https://example.com/api")
            assert result["status_code"] == 200
            assert result["cookies_used"] == []

    def test_fetch_error_handling(self):
        client = HttpClient(base_timeout=5)
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.request.side_effect = Exception(
                "Connection refused"
            )
            result = client.fetch("https://invalid.example.com/")
            assert result["status_code"] == -1
            assert result["error"] == "Connection refused"

    def test_fetch_post_with_body(self):
        mock_response = MagicMock()
        mock_response.url = "https://example.com/api"
        mock_response.status_code = 201
        mock_response.headers = {}
        mock_response.text = "created"

        client = HttpClient(base_timeout=10)
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response
            result = client.fetch(
                "https://example.com/api",
                method="POST",
                data={"key": "value"},
            )
            assert result["status_code"] == 201
            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args[1]["method"] == "POST"
