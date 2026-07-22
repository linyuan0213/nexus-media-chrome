"""Session + SessionManager — DrissionPage 4.2 兼容，手动 CookieStore 隔离。"""

import json
import time
from typing import Any, Dict, List, Optional, cast
from urllib.parse import urlparse

from DrissionPage import Chromium
from DrissionPage._pages.chromium_tab import ChromiumTab
from loguru import logger

from src.challenge.resolver import ChallengeOrchestrator
from src.config.settings import (
    CHALLENGE_TIMEOUT,
    MAX_SESSIONS,
    SESSION_TTL,
    TURNSTILE_HOOK_JS,
)
from src.core.cookie_store import CookieStore
from src.core.fingerprint import FingerprintManager


class Session:
    def __init__(
        self,
        session_id: str,
        browser: Chromium,
        fingerprint: FingerprintManager,
        user_agent: Optional[str] = None,
        proxy: Optional[str] = None,
    ):
        self.id = session_id
        self._browser = browser
        self.fingerprint = fingerprint
        self.cookie_store = CookieStore()
        self._user_agent = user_agent
        self._proxy = proxy
        self._tabs: Dict[str, ChromiumTab] = {}
        self._active_tab_name: Optional[str] = None
        self._tab_counter = 0
        self._last_used_at = time.monotonic()
        logger.info(f"[Session:{self.id}] 已创建 (fingerprint={fingerprint.profile_name})")

    @property
    def last_used_at(self) -> float:
        return self._last_used_at

    def touch(self) -> None:
        """更新会话最后使用时间。"""
        self._last_used_at = time.monotonic()

    def _auto_tab_name(self) -> str:
        self._tab_counter += 1
        return f"tab_{self._tab_counter}"

    def _create_tab_internal(
        self, url: str, tab_name: Optional[str] = None,
        cookie: Optional[str] = None, referer: Optional[str] = None,
        local_storage: Optional[Dict[str, str]] = None,
    ) -> ChromiumTab:
        name = tab_name or self._auto_tab_name()
        if name in self._tabs:
            raise ValueError(f"标签页 '{name}' 已存在")

        # 先创建空白标签页，注入指纹 JS 后再导航，确保首次加载也带伪装
        tab = self._browser.new_tab()
        tab.set.load_mode.none()  # type: ignore[union-attr]

        init_js = self.fingerprint.get_init_js()
        if init_js:
            tab.add_init_js(init_js)
        if TURNSTILE_HOOK_JS:
            tab.add_init_js(TURNSTILE_HOOK_JS)

        if self._user_agent:
            tab.set.user_agent(self._user_agent)  # type: ignore[union-attr]
        if cookie:
            cookies = self._parse_cookie_header(cookie)
            domain = urlparse(url).netloc
            for c in cookies:
                c.setdefault("domain", domain)
                c.setdefault("path", "/")
            tab.set.cookies(cookies)  # type: ignore[union-attr]
        if referer:
            tab.set.headers({"Referer": referer})  # type: ignore[union-attr]
        if local_storage:
            try:
                for key, value in local_storage.items():
                    escaped_key = key.replace("'", "\\'")
                    escaped_value = value.replace("'", "\\'")
                    tab.run_js(f"localStorage.setItem('{escaped_key}', '{escaped_value}')")  # type: ignore[union-attr]
            except Exception as e:
                logger.warning(f"[Session:{self.id}] 设置标签页 LocalStorage 失败: {e}")
        if self._proxy:
            try:
                tab.set.proxy(self._proxy)  # type: ignore[union-attr]
            except Exception as e:
                logger.warning(f"[Session:{self.id}] 设置标签页代理失败: {e}")

        tab.get(url)  # type: ignore[union-attr]
        tab.wait(3)
        self._tabs[name] = tab
        self._active_tab_name = name
        return tab

    def navigate(self, url: str, tab_name: Optional[str] = None,
                 cookie: Optional[str] = None, referer: Optional[str] = None,
                 timeout: int = CHALLENGE_TIMEOUT,
                 local_storage: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        self.touch()
        if tab_name is None and self._active_tab_name is not None:
            self.close_tab(self._active_tab_name)
        elif tab_name is not None and tab_name in self._tabs:
            self.close_tab(tab_name)
        tab = self._create_tab_internal(url, tab_name, cookie=cookie, referer=referer,
                                        local_storage=local_storage)
        orchestrator = ChallengeOrchestrator(timeout=timeout)
        challenge_result = orchestrator.resolve(tab)
        domain = urlparse(url).netloc
        html = ""
        try:
            html = tab.html
            cookies = tab.cookies()
            if cookies:
                self._store_cookies(domain, cookies)
        except Exception:
            try:
                browser_any: Any = self._browser
                result = browser_any._run_cdp("Storage.getCookies")
                self._store_cookies_from_cdp(domain, result.get("cookies", []))
            except Exception:
                logger.debug("CDP 获取 Cookies 失败，跳过")

        page_url = url
        page_title = ""
        try:
            page_url = tab.url
            page_title = tab.title
        except Exception:
            logger.debug("读取页面 URL/标题失败，使用原始 URL")

        return {
            "url": page_url, "title": page_title, "html": html,
            "cookies": self.cookie_store.as_dict(domain),
            "cookie_header": self.cookie_store.as_header(domain),
            "challenge": challenge_result,
        }

    def _store_cookies(self, domain: str, cookies: List[Dict[str, str]]) -> None:
        for c in cookies:
            self.cookie_store.store(domain, [{
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", domain),
                "path": c.get("path", "/"),
            }])

    def _store_cookies_from_cdp(self, domain: str, cookies: List[Dict[str, str]]) -> None:
        for c in cookies:
            self.cookie_store.store(domain, [{
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", domain),
                "path": c.get("path", "/"),
            }])

    @staticmethod
    def _parse_cookie_header(cookie_str: str) -> List[Dict[str, str]]:
        """把 Cookie 头字符串解析为 DrissionPage 可识别的 cookie 列表。"""
        cookies: List[Dict[str, str]] = []
        if not cookie_str:
            return cookies
        for part in cookie_str.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, value = part.split("=", 1)
            cookies.append({"name": name.strip(), "value": value.strip()})
        return cookies

    def _merge_cookies(
        self,
        domain: str,
        cookie_header: Optional[str],
    ) -> List[Dict[str, str]]:
        """合并 cookie_store 与用户传入的 Cookie。"""
        cookies = self.cookie_store.get(domain)
        for c in cookies:
            c.setdefault("domain", domain)
            c.setdefault("path", "/")
        if cookie_header:
            user_cookies = self._parse_cookie_header(cookie_header)
            existing_names = {c.get("name") for c in cookies}
            for c in user_cookies:
                if c.get("name") not in existing_names:
                    c.setdefault("domain", domain)
                    c.setdefault("path", "/")
                    cookies.append(c)
        return cookies

    def _create_fetch_tab(
        self,
        url: str,
        cookies: Optional[List[Dict[str, str]]] = None,
        referer: Optional[str] = None,
    ) -> ChromiumTab:
        """创建用于 browser_fetch 的标签页，不自动导航。"""
        tab = self._browser.new_tab()
        tab.set.load_mode.none()  # type: ignore[union-attr]

        init_js = self.fingerprint.get_init_js()
        if init_js:
            tab.add_init_js(init_js)
        if TURNSTILE_HOOK_JS:
            tab.add_init_js(TURNSTILE_HOOK_JS)

        if self._user_agent:
            tab.set.user_agent(self._user_agent)  # type: ignore[union-attr]
        if cookies:
            tab.set.cookies(cookies)  # type: ignore[union-attr]
        if referer:
            tab.set.headers({"Referer": referer})  # type: ignore[union-attr]
        if self._proxy:
            try:
                tab.set.proxy(self._proxy)  # type: ignore[union-attr]
            except Exception as e:
                logger.warning(f"[Session:{self.id}] 设置标签页代理失败: {e}")

        return tab

    def _browser_fetch_get(
        self,
        url: str,
        cookie: Optional[str],
        headers: Optional[Dict[str, str]],
        timeout: int,
    ) -> Dict[str, Any]:
        """使用浏览器网络栈通过 GET 请求 URL，并获取原始响应体。

        直接复用 navigate 的过盾能力，取回页面 HTML 作为原始响应体。
        """
        nav_result = self.navigate(url, cookie=cookie, timeout=timeout)
        return {
            "url": nav_result.get("url", url),
            "status_code": 200,
            "headers": {},
            "body": nav_result.get("html", ""),
            "challenge": nav_result.get("challenge"),
        }


    def _browser_fetch_js(
        self,
        url: str,
        cookie: Optional[str],
        method: str,
        headers: Optional[Dict[str, str]],
        data: Any,
        timeout: int,
    ) -> Dict[str, Any]:
        """非 GET 请求：先导航到同 origin 过盾，再用浏览器内 fetch 发送请求。"""
        self.touch()
        domain = urlparse(url).netloc
        cookies = self._merge_cookies(domain, cookie)
        tab = self._create_fetch_tab(url, cookies=cookies)
        name = self._auto_tab_name()
        self._tabs[name] = tab
        self._active_tab_name = name

        try:
            tab.get(url)  # type: ignore[union-attr]
            tab.wait(3)

            orchestrator = ChallengeOrchestrator(timeout=timeout)
            challenge_result = orchestrator.resolve(tab)

            headers_json = json.dumps(headers or {})
            body_str = data if isinstance(data, str) else json.dumps(data) if data is not None else ""

            script = f"""
            async () => {{
                try {{
                    const response = await fetch({json.dumps(url)}, {{
                        method: {json.dumps(method)},
                        headers: {headers_json},
                        body: {json.dumps(body_str)},
                        credentials: 'include'
                    }});
                    const text = await response.text();
                    const headers = {{}};
                    response.headers.forEach((value, key) => {{ headers[key] = value; }});
                    return {{
                        status: response.status,
                        headers: headers,
                        body: text,
                        url: response.url
                    }};
                }} catch (e) {{
                    return {{error: e.message}};
                }}
            }}
            """

            try:
                tab_any: Any = tab
                result: Any = tab_any.run_async_js(script, as_expr=False)
            except Exception as e:
                result = {"error": str(e)}

            if not result:
                result = {"error": "JS fetch did not return a result"}

            result = cast(Dict[str, Any], result)
            result_dict = cast(Dict[str, Any], result)

            if "error" in result_dict:
                raise RuntimeError(f"JS fetch failed: {result_dict.get('error')}")

            try:
                cookies = tab.cookies()
                if cookies:
                    self._store_cookies(domain, cookies)
            except Exception:
                try:
                    browser_any: Any = self._browser
                    result_cdp = cast(Dict[str, Any], browser_any._run_cdp("Storage.getCookies"))
                    self._store_cookies_from_cdp(domain, result_cdp.get("cookies", []))
                except Exception:
                    logger.debug("fetch 后 CDP 获取 Cookies 失败，跳过")

            return {
                "url": result_dict.get("url", tab.url),
                "status_code": result_dict.get("status", 200),
                "headers": result_dict.get("headers", {}),
                "body": result_dict.get("body", ""),
                "challenge": challenge_result,
            }
        finally:
            try:
                self.close_tab(name)
            except Exception as e:
                logger.debug(f"[Session:{self.id}] 关闭 fetch 标签页 {name} 失败: {e}")

    def browser_fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Any = None,
        cookie: Optional[str] = None,
        timeout: int = CHALLENGE_TIMEOUT,
    ) -> Dict[str, Any]:
        """使用浏览器网络栈请求 URL，自动过盾并返回原始响应体。"""
        domain = urlparse(url).netloc
        cookie_header = self.cookie_store.as_header(domain)
        if cookie:
            cookie_header = f"{cookie_header}; {cookie}" if cookie_header else cookie

        if method.upper() == "GET":
            return self._browser_fetch_get(url, cookie_header, headers, timeout)

        return self._browser_fetch_js(url, cookie_header, method, headers, data, timeout)

    def get_html(self) -> Dict[str, Any]:
        self.touch()
        tab = self._get_active_tab()
        return {"url": tab.url, "html": tab.html}

    def get_cookies(self, domain: Optional[str] = None) -> Dict[str, Any]:
        self.touch()
        if domain:
            return {domain: self.cookie_store.as_dict(domain)}
        return self.cookie_store.as_full_dict()

    def click(self, selector: str) -> None:
        self.touch()
        self._get_active_tab().ele(selector).click(by_js=None)  # type: ignore[union-attr]

    def input_text(self, selector: str, text: str) -> None:
        self.touch()
        ele = self._get_active_tab().ele(selector)
        ele.clear()  # type: ignore[union-attr]
        ele.input(text)  # type: ignore[union-attr]

    def execute(self, script: str) -> Any:
        self.touch()
        return self._get_active_tab().run_js(script)  # type: ignore[union-attr]

    def close_tab(self, tab_name: str) -> None:
        if tab_name not in self._tabs:
            raise ValueError(f"标签页 '{tab_name}' 未找到")
        tab = self._tabs.pop(tab_name)
        if self._active_tab_name == tab_name:
            self._active_tab_name = next(iter(self._tabs), None)
        try:
            tab.close()
        except Exception:
            logger.warning(f"[Session:{self.id}] 常规关闭标签页 {tab_name} 失败，尝试 CDP 关闭")
            try:
                target_id = getattr(tab, "tab_id", None) or tab._target_id
                browser_any: Any = self._browser
                browser_any._run_cdp("Target.CloseTarget", {"targetId": target_id})
            except Exception:
                logger.warning(f"[Session:{self.id}] CDP 关闭标签页 {tab_name} 也失败，标签页可能已孤儿")

    def close_all_tabs(self) -> None:
        for name in list(self._tabs.keys()):
            self.close_tab(name)

    def _get_active_tab(self) -> ChromiumTab:
        if not self._active_tab_name or self._active_tab_name not in self._tabs:
            raise ValueError("没有活跃的标签页，请先调用 navigate")
        return self._tabs[self._active_tab_name]

    def close(self) -> None:
        self.close_all_tabs()
        self.cookie_store.clear()
        logger.info(f"[Session:{self.id}] 已关闭")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "fingerprint": self.fingerprint.profile_name,
            "tabs": list(self._tabs.keys()), "active_tab": self._active_tab_name,
            "cookie_domains": self.cookie_store.list_domains(),
        }


class SessionManager:
    def __init__(self, browser: Chromium, max_sessions: int = MAX_SESSIONS,
                 session_ttl: int = SESSION_TTL):
        self._browser = browser
        self._sessions: Dict[str, Session] = {}
        self._max_sessions = max_sessions
        self._session_ttl = session_ttl

    def create(self, session_id: str, fingerprint_profile: Optional[str] = None,
               user_agent: Optional[str] = None, proxy: Optional[str] = None) -> Session:
        if session_id in self._sessions:
            raise ValueError(f"会话 '{session_id}' 已存在")
        if len(self._sessions) >= self._max_sessions:
            oldest_id = min(self._sessions, key=lambda sid: self._sessions[sid].last_used_at)
            logger.warning(
                f"会话数量达到上限 {self._max_sessions}，移除最旧会话 {oldest_id}"
            )
            self.delete(oldest_id)
        fingerprint = FingerprintManager(fingerprint_profile)
        session = Session(
            session_id=session_id, browser=self._browser,
            fingerprint=fingerprint, user_agent=user_agent, proxy=proxy,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            raise ValueError(f"会话 '{session_id}' 未找到")
        session = self._sessions[session_id]
        session.touch()
        return session

    def list_all(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self._sessions.values()]

    def delete(self, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话 '{session_id}' 未找到")
        self._sessions.pop(session_id).close()

    def delete_all(self) -> None:
        for sid in list(self._sessions.keys()):
            self.delete(sid)

    def delete_expired(self, max_idle_seconds: Optional[int] = None) -> int:
        """清理超过空闲时间的会话，返回清理数量。"""
        threshold = max_idle_seconds if max_idle_seconds is not None else self._session_ttl
        now = time.monotonic()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.last_used_at > threshold
        ]
        for sid in expired:
            self.delete(sid)
        return len(expired)


session_manager: Optional[SessionManager] = None
