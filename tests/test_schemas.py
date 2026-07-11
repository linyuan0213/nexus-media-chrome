"""API Schema 单元测试。"""

import pytest
from pydantic import ValidationError

from src.api.schemas import (
    ApiResponse,
    ClickRequest,
    CreateSessionRequest,
    ExecuteRequest,
    HttpFetchRequest,
    InputRequest,
    NavigateRequest,
)


class TestCreateSessionRequest:
    def test_valid_minimal(self):
        req = CreateSessionRequest(session_id="test")  # type: ignore[call-arg]
        assert req.session_id == "test"
        assert req.fingerprint_profile == "stealth"

    def test_valid_full(self):
        req = CreateSessionRequest(
            session_id="test",
            fingerprint_profile="paranoid",
            user_agent="Mozilla/5.0",
            proxy="http://127.0.0.1:8080",
        )
        assert req.fingerprint_profile == "paranoid"
        assert req.proxy == "http://127.0.0.1:8080"

    def test_missing_session_id(self):
        with pytest.raises(ValidationError):
            CreateSessionRequest()  # type: ignore[call-arg]


class TestNavigateRequest:
    def test_valid_minimal(self):
        req = NavigateRequest(url="https://example.com")  # type: ignore[call-arg]
        assert req.url == "https://example.com"
        assert req.timeout == 30

    def test_valid_full(self):
        req = NavigateRequest(
            url="https://example.com",
            tab_name="my-tab",
            cookie="a=1; b=2",
            local_storage=None,
            referer="https://google.com",
            timeout=60,
        )
        assert req.tab_name == "my-tab"
        assert req.referer == "https://google.com"

    def test_missing_url(self):
        with pytest.raises(ValidationError):
            NavigateRequest()  # type: ignore[call-arg]


class TestClickRequest:
    def test_valid(self):
        req = ClickRequest(selector="#btn")
        assert req.selector == "#btn"


class TestInputRequest:
    def test_valid(self):
        req = InputRequest(selector="#input", text="hello")
        assert req.text == "hello"


class TestExecuteRequest:
    def test_valid(self):
        req = ExecuteRequest(script="return 1+1")
        assert req.script == "return 1+1"


class TestHttpFetchRequest:
    def test_valid_minimal(self):
        req = HttpFetchRequest(url="https://example.com")  # type: ignore[call-arg]
        assert req.method == "GET"

    def test_valid_post(self):
        req = HttpFetchRequest(url="https://example.com", method="POST", data={"x": 1})  # type: ignore[call-arg]
        assert req.data == {"x": 1}


class TestApiResponse:
    def test_success(self):
        resp = ApiResponse(code=0, message="ok", data={"key": "value"})
        assert resp.code == 0
        assert resp.data == {"key": "value"}

    def test_error(self):
        resp = ApiResponse(code=-1, message="error")  # type: ignore[call-arg]
        assert resp.code == -1
