"""挑战解析器 resolve 逻辑单元测试 — 使用 mock tab。"""

import time
from unittest.mock import MagicMock

import pytest

from src.challenge.cloudflare import CloudflareResolver
from src.challenge.five_second_shield import FiveSecondShieldResolver
from src.challenge.generic import GenericResolver
from src.challenge.leichi import LeichiResolver

CF_PAGE = "<html><head><title>Just a moment...</title></head><body><div id='cf-challenge-running'></div></body></html>"
CF_BOX_PAGE = "<html><head><title>Example</title></head><body><input name='cf-turnstile-response'></body></html>"
FIVE_SEC_PAGE = "<html><head><title>安全检查中...</title></head><body><div id='sec'>5</div></body></html>"
LEICHI_PAGE = "<html><head><title>雷池</title></head><body><div id='safeline-block'></div></body></html>"
NORMAL_PAGE = "<html><head><title>Normal Page</title></head><body><p>Hello</p></body></html>"


def make_tab(html_sequence=None):
    tab = MagicMock()
    if html_sequence is None:
        html_sequence = [NORMAL_PAGE]
    iter_html = iter(html_sequence)
    tab.html = property(lambda self: next(iter_html, NORMAL_PAGE))
    type(tab).html = tab.html
    return tab


class TestResolverTimeout:
    def test_five_second_respects_timeout(self):
        tab = MagicMock()
        tab.html = FIVE_SEC_PAGE
        resolver = FiveSecondShieldResolver()
        start = time.monotonic()
        result = resolver.resolve(tab, timeout=2)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 5  # 不应硬编码等待 7 秒

    def test_leichi_respects_timeout(self):
        tab = MagicMock()
        tab.html = LEICHI_PAGE
        resolver = LeichiResolver()
        start = time.monotonic()
        result = resolver.resolve(tab, timeout=2)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 5

    def test_generic_respects_timeout(self):
        tab = MagicMock()
        tab.html = "<html><head><title>Access denied</title></head><body><div class='challenge-container'></div></body></html>"
        resolver = GenericResolver()
        start = time.monotonic()
        result = resolver.resolve(tab, timeout=2)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 5


class TestCloudflareResolve:
    def test_no_challenge_returns_true(self):
        tab = MagicMock()
        tab.html = NORMAL_PAGE
        resolver = CloudflareResolver()
        assert resolver.resolve(tab, timeout=2) is True
        tab.wait.assert_called()

    def test_managed_challenge_polling(self):
        tab = MagicMock()
        tab.html = CF_PAGE
        resolver = CloudflareResolver()
        # 由于 _solve_standard 会调用 sync_cf_retry，mock 它
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.challenge.cloudflare._is_managed_challenge", lambda x: True)
            result = resolver.resolve(tab, timeout=1)
        # Managed Challenge 会轮询，超时返回 False
        assert result is False

    def test_challenge_cleared_returns_true(self):
        tab = MagicMock()
        # 第一页是 challenge，之后变成正常页面
        htmls = [CF_PAGE, CF_PAGE, NORMAL_PAGE]
        tab.html = property(lambda self: htmls.pop(0) if htmls else NORMAL_PAGE)
        type(tab).html = tab.html
        resolver = CloudflareResolver()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.challenge.cloudflare._is_managed_challenge", lambda x: True)
            result = resolver.resolve(tab, timeout=5)
        assert result is True
