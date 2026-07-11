"""挑战检测单元测试 — 纯 HTML 解析，不需要浏览器。"""


from src.config.settings import (
    CHALLENGE_TYPE_CLOUDFLARE,
    CHALLENGE_TYPE_FIVE_SECOND,
    CHALLENGE_TYPE_GENERIC,
    CHALLENGE_TYPE_LEICHI,
)

# HTML 片段
CF_PAGE = "<html><head><title>Just a moment...</title></head><body><div id='cf-challenge-running'></div></body></html>"
CF_BOX_PAGE = "<html><head><title>Example</title></head><body><input name='cf-turnstile-response'></body></html>"
FIVE_SEC_PAGE = "<html><head><title>安全检查中...</title></head><body><div id='sec'>5</div></body></html>"
LEICHI_PAGE = "<html><head><title>雷池</title></head><body><div id='safeline-block'></div></body></html>"
NORMAL_PAGE = "<html><head><title>Normal Page</title></head><body><p>Hello</p></body></html>"


class TestCloudflareDetect:
    def test_detect_standard(self):
        from src.challenge.cloudflare import _under_cf_challenge

        assert _under_cf_challenge(CF_PAGE) is True

    def test_detect_japanese(self):
        from src.challenge.cloudflare import _under_cf_challenge

        html = "<html><head><title>请稍候…</title></head><body></body></html>"
        assert _under_cf_challenge(html) is True

    def test_detect_box(self):
        from src.challenge.cloudflare import _under_cf_box_challenge

        assert _under_cf_box_challenge(CF_BOX_PAGE) is True

    def test_no_detect_on_normal(self):
        from src.challenge.cloudflare import _under_cf_box_challenge, _under_cf_challenge

        assert _under_cf_challenge(NORMAL_PAGE) is False
        assert _under_cf_box_challenge(NORMAL_PAGE) is False

    def test_challenge_type(self):
        from src.challenge.cloudflare import CloudflareResolver

        resolver = CloudflareResolver()
        assert resolver.challenge_type == CHALLENGE_TYPE_CLOUDFLARE


class TestFiveSecondDetect:
    def test_detect_by_selector(self):
        from pyquery import PyQuery

        from src.config.settings import FIVE_SECOND_SELECTORS

        doc = PyQuery(FIVE_SEC_PAGE)
        found = any(doc(s) for s in FIVE_SECOND_SELECTORS)
        assert found is True

    def test_no_detect_on_normal(self):
        from pyquery import PyQuery

        from src.config.settings import FIVE_SECOND_SELECTORS

        doc = PyQuery(NORMAL_PAGE)
        found = any(doc(s) for s in FIVE_SECOND_SELECTORS)
        assert found is False

    def test_challenge_type(self):
        from src.challenge.five_second_shield import FiveSecondShieldResolver

        resolver = FiveSecondShieldResolver()
        assert resolver.challenge_type == CHALLENGE_TYPE_FIVE_SECOND


class TestLeichiDetect:
    def test_detect_by_selector(self):
        from pyquery import PyQuery

        from src.config.settings import LEICHI_SELECTORS

        doc = PyQuery(LEICHI_PAGE)
        found = any(doc(s) for s in LEICHI_SELECTORS)
        assert found is True

    def test_challenge_type(self):
        from src.challenge.leichi import LeichiResolver

        resolver = LeichiResolver()
        assert resolver.challenge_type == CHALLENGE_TYPE_LEICHI


class TestGenericDetect:
    def test_detect_by_selector(self):
        from pyquery import PyQuery

        from src.config.settings import CHALLENGE_SELECTORS, GENERIC_CHALLENGE_SELECTORS

        html = "<html><head><title>Access denied</title></head><body><div class='challenge-container'></div></body></html>"
        doc = PyQuery(html)
        all_selectors = CHALLENGE_SELECTORS + GENERIC_CHALLENGE_SELECTORS
        found = any(doc(s) for s in all_selectors)
        assert found is True

    def test_challenge_type(self):
        from src.challenge.generic import GenericResolver

        resolver = GenericResolver()
        assert resolver.challenge_type == CHALLENGE_TYPE_GENERIC


class TestChallengeOrchestratorInit:
    def test_creates_resolvers(self):
        from src.challenge.resolver import ChallengeOrchestrator

        orchestrator = ChallengeOrchestrator(timeout=30)
        assert len(orchestrator._resolvers) == 4

    def test_resolve_no_challenge(self):
        from unittest.mock import MagicMock

        from src.challenge.resolver import ChallengeOrchestrator

        orchestrator = ChallengeOrchestrator(timeout=5)
        tab = MagicMock()
        tab.html = NORMAL_PAGE
        result = orchestrator.resolve(tab)
        assert result["detected"] is False
        assert result["solved"] is True
