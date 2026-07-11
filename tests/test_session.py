"""Session 模块单元测试 — 使用 mock 浏览器，无需真实 Chrome。"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.fingerprint import FingerprintManager
from src.core.session import Session, SessionManager


@pytest.fixture
def mock_browser():
    return MagicMock()


@pytest.fixture
def mock_tab():
    tab = MagicMock()
    tab.html = "<html><body>hello</body></html>"
    tab.url = "https://example.com/"
    tab.title = "Example"
    tab.cookies.return_value = [
        {"name": "session_id", "value": "abc123", "domain": ".example.com", "path": "/"},
    ]
    # 设置 ele 返回的 mock 元素，支持 click / clear / input
    ele_mock = MagicMock()
    tab.ele.return_value = ele_mock
    return tab


class TestSessionManager:
    def test_create_and_get(self, mock_browser):
        sm = SessionManager(mock_browser)
        session = sm.create("test-session", fingerprint_profile="stealth")
        assert sm.get("test-session") is session
        assert session.fingerprint.profile_name == "stealth"

    def test_create_duplicate_raises(self, mock_browser):
        sm = SessionManager(mock_browser)
        sm.create("test-session")
        with pytest.raises(ValueError):
            sm.create("test-session")

    def test_get_missing_raises(self, mock_browser):
        sm = SessionManager(mock_browser)
        with pytest.raises(ValueError):
            sm.get("missing")

    def test_list_and_delete(self, mock_browser):
        sm = SessionManager(mock_browser)
        sm.create("a")
        sm.create("b")
        assert len(sm.list_all()) == 2
        sm.delete("a")
        assert len(sm.list_all()) == 1
        with pytest.raises(ValueError):
            sm.get("a")


class TestSessionNavigate:
    def test_navigate_creates_tab_and_stores_cookies(self, mock_browser, mock_tab):
        mock_browser.new_tab.return_value = mock_tab
        session = Session("s1", mock_browser, FingerprintManager("stealth"))

        with patch("src.core.session.ChallengeOrchestrator") as MockOrchestrator:
            MockOrchestrator.return_value.resolve.return_value = {
                "detected": False, "type": "none", "solved": True, "duration_ms": 0
            }
            result = session.navigate("https://example.com/")

        mock_browser.new_tab.assert_called_once()
        assert result["url"] == "https://example.com/"
        assert result["cookies"]["session_id"] == "abc123"
        assert session.cookie_store.as_dict("example.com")["session_id"] == "abc123"

    def test_navigate_init_js_before_load(self, mock_browser, mock_tab):
        mock_browser.new_tab.return_value = mock_tab
        session = Session("s1", mock_browser, FingerprintManager("stealth"))

        with patch("src.core.session.ChallengeOrchestrator") as MockOrchestrator:
            MockOrchestrator.return_value.resolve.return_value = {
                "detected": False, "type": "none", "solved": True, "duration_ms": 0
            }
            session.navigate("https://example.com/")

        assert mock_tab.add_init_js.call_count >= 2
        assert mock_tab.get.called


class TestSessionProxy:
    def test_proxy_applied_to_tab(self, mock_browser, mock_tab):
        mock_browser.new_tab.return_value = mock_tab
        session = Session("s1", mock_browser, FingerprintManager("stealth"), proxy="http://proxy:8080")

        with patch("src.core.session.ChallengeOrchestrator") as MockOrchestrator:
            MockOrchestrator.return_value.resolve.return_value = {
                "detected": False, "type": "none", "solved": True, "duration_ms": 0
            }
            session.navigate("https://example.com/")

        mock_tab.set.proxy.assert_called_once_with("http://proxy:8080")

    def test_proxy_set_failure_warns(self, mock_browser, mock_tab, caplog):
        mock_tab.set.proxy.side_effect = RuntimeError("not supported")
        mock_browser.new_tab.return_value = mock_tab
        session = Session("s1", mock_browser, FingerprintManager("stealth"), proxy="http://proxy:8080")

        with patch("src.core.session.ChallengeOrchestrator") as MockOrchestrator:
            MockOrchestrator.return_value.resolve.return_value = {
                "detected": False, "type": "none", "solved": True, "duration_ms": 0
            }
            session.navigate("https://example.com/")  # 不应抛异常

        mock_tab.set.proxy.assert_called_once()


class TestSessionInteraction:
    def test_click(self, mock_browser, mock_tab):
        mock_browser.new_tab.return_value = mock_tab
        session = Session("s1", mock_browser, FingerprintManager("stealth"))
        with patch("src.core.session.ChallengeOrchestrator") as MockOrchestrator:
            MockOrchestrator.return_value.resolve.return_value = {
                "detected": False, "type": "none", "solved": True, "duration_ms": 0
            }
            session.navigate("https://example.com/")
        session.click("#btn")
        mock_tab.ele.assert_called_once_with("#btn")
        mock_tab.ele.return_value.click.assert_called_once_with(by_js=None)

    def test_input_text(self, mock_browser, mock_tab):
        mock_browser.new_tab.return_value = mock_tab
        session = Session("s1", mock_browser, FingerprintManager("stealth"))
        with patch("src.core.session.ChallengeOrchestrator") as MockOrchestrator:
            MockOrchestrator.return_value.resolve.return_value = {
                "detected": False, "type": "none", "solved": True, "duration_ms": 0
            }
            session.navigate("https://example.com/")
        session.input_text("#search", "keyword")
        mock_tab.ele.assert_called_once_with("#search")
        mock_tab.ele.return_value.clear.assert_called_once()
        mock_tab.ele.return_value.input.assert_called_once_with("keyword")

    def test_execute(self, mock_browser, mock_tab):
        mock_browser.new_tab.return_value = mock_tab
        session = Session("s1", mock_browser, FingerprintManager("stealth"))
        with patch("src.core.session.ChallengeOrchestrator") as MockOrchestrator:
            MockOrchestrator.return_value.resolve.return_value = {
                "detected": False, "type": "none", "solved": True, "duration_ms": 0
            }
            session.navigate("https://example.com/")
        session.execute("return document.title")
        mock_tab.run_js.assert_called_once_with("return document.title")


class TestSessionClose:
    def test_close_tab(self, mock_browser, mock_tab):
        mock_browser.new_tab.return_value = mock_tab
        session = Session("s1", mock_browser, FingerprintManager("stealth"))
        with patch("src.core.session.ChallengeOrchestrator") as MockOrchestrator:
            MockOrchestrator.return_value.resolve.return_value = {
                "detected": False, "type": "none", "solved": True, "duration_ms": 0
            }
            session.navigate("https://example.com/")
        session.close_tab("tab_1")
        mock_tab.close.assert_called_once()
        assert session._active_tab_name is None
