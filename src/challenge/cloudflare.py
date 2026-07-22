"""Cloudflare 挑战解析器 — 标准挑战 + Turnstile 盒子 + Managed Challenge。"""

import time

from DrissionPage._pages.chromium_tab import ChromiumTab
from loguru import logger
from pyquery import PyQuery as pq  # type: ignore[import-untyped]

from src.challenge.base import ChallengeResolver
from src.config.settings import (
    CF_CHALLENGE_SELECTORS,
    CHALLENGE_TYPE_CLOUDFLARE,
)
from src.utils.challenge_utils import sync_cf_box_retry, sync_cf_retry

CF_TITLES = {"just a moment...", "请稍候…"}


def _page_title(html_text: str) -> str:
    if not html_text:
        return ""
    return str(pq(html_text)("title").text()).lower()  # type: ignore


def _under_cf_challenge(html_text: str) -> bool:
    if not html_text:
        return False
    if _page_title(html_text) in CF_TITLES:
        return True
    doc = pq(html_text)
    for selector in CF_CHALLENGE_SELECTORS:
        if doc(selector):
            return True
    return False


def _under_cf_box_challenge(html_text: str) -> bool:
    if not html_text:
        return False
    return _is_turnstile_challenge(html_text)


def _is_managed_challenge(html_text: str) -> bool:
    """检测是否为 Cloudflare Managed Challenge（JS 自动求解，无需交互）。"""
    if not html_text:
        return False
    if "challenges.cloudflare.com" in html_text:
        return True
    doc = pq(html_text)
    if doc('script[src*="challenges.cloudflare.com"]'):
        return True
    return False


def _is_turnstile_challenge(html_text: str) -> bool:
    if not html_text:
        return False
    if "cf-turnstile-response" in html_text:
        return True
    doc = pq(html_text)
    if doc('input[name="cf-turnstile-response"]'):
        return True
    return False


class CloudflareResolver(ChallengeResolver):
    @property
    def challenge_type(self) -> str:
        return CHALLENGE_TYPE_CLOUDFLARE

    def detect(self, tab: ChromiumTab) -> bool:
        try:
            html = tab.html
        except Exception:
            return False
        return _under_cf_challenge(html) or _under_cf_box_challenge(html)

    def resolve(self, tab: ChromiumTab, timeout: int = 30) -> bool:
        """尝试解析 Cloudflare 挑战。"""
        try:
            tab.wait(2)
            html = tab.html
        except Exception:
            html = ""

        if not html:
            return self._wait_challenge_cleared(tab, timeout)

        if not _under_cf_challenge(html) and not _under_cf_box_challenge(html):
            return True

        if _under_cf_box_challenge(html):
            return self._solve_box(tab, timeout)

        if _is_managed_challenge(html):
            return self._wait_managed(tab, timeout)

        return self._solve_standard(tab, timeout)

    def _wait_challenge_cleared(self, tab: ChromiumTab, timeout: int) -> bool:
        """通用轮询：等待页面不再处于 Cloudflare 挑战状态。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                html = tab.html
            except Exception:
                html = ""
            if not _under_cf_challenge(html) and not _under_cf_box_challenge(html):
                return True
            time.sleep(1)
        return False

    def _wait_managed(self, tab: ChromiumTab, timeout: int) -> bool:
        """Managed Challenge：Cloudflare JS 自动求解，只需等待并轮询。"""
        logger.debug("Cloudflare Managed Challenge，等待 JS 自动求解...")
        return self._wait_challenge_cleared(tab, timeout)

    def _solve_standard(self, tab: ChromiumTab, timeout: int) -> bool:
        """标准 Cloudflare 挑战：尝试点击 Turnstile 复选框。"""
        logger.debug("Cloudflare 标准挑战，尝试点击验证按钮...")
        tries = max(1, min(timeout // 10, 2))
        success, _ = sync_cf_retry(tab, tries=tries)
        if success:
            return True
        # 兜底：再等待挑战自动清除
        return self._wait_challenge_cleared(tab, timeout)

    def _solve_box(self, tab: ChromiumTab, timeout: int) -> bool:
        """Turnstile 盒子挑战：尝试点击盒子内的验证按钮。"""
        logger.debug("Cloudflare Turnstile 盒子挑战，尝试点击...")
        tries = max(1, min(timeout // 10, 2))
        success, _ = sync_cf_box_retry(tab, tries=tries)
        if success:
            return True
        return self._wait_challenge_cleared(tab, timeout)
