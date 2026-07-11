"""HTTP 客户端 — 基于 httpx，与 Session 的 CookieStore 双向同步 Cookie。"""

from http.cookies import SimpleCookie
from typing import Any, Dict, List, Optional, cast
from urllib.parse import urlparse

import httpx
from loguru import logger


class HttpClient:
    def __init__(self, base_timeout: int = 30, max_redirects: int = 10):
        self.base_timeout = base_timeout
        self.max_redirects = max_redirects

    def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Any = None,
        cookie_store: Any = None,
        timeout: Optional[int] = None,
        follow_redirects: bool = True,
    ) -> Dict[str, Any]:
        merged_headers = dict(headers or {})

        used_cookies: List[str] = []
        if cookie_store is not None:
            domain = urlparse(url).netloc
            cookie_header = cookie_store.as_header(domain)
            if cookie_header:
                existing = merged_headers.get("Cookie", "")
                merged_headers["Cookie"] = (
                    f"{existing}; {cookie_header}" if existing else cookie_header
                )
                used_cookies = list(cookie_store.as_dict(domain).keys())

        if timeout is None:
            timeout = self.base_timeout

        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=follow_redirects,
                max_redirects=self.max_redirects,
            ) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=merged_headers,
                    content=data if isinstance(data, (str, bytes)) else None,
                    json=cast(Dict[str, Any], data) if isinstance(data, dict) else None,
                )
                self._update_cookie_store(response, url, cookie_store)
                return {
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text,
                    "cookies_used": used_cookies,
                }
        except Exception as e:
            logger.error(f"HTTP 请求失败: {url} - {e}")
            return {
                "url": url,
                "status_code": -1,
                "headers": {},
                "body": "",
                "cookies_used": used_cookies,
                "error": str(e),
            }

    @staticmethod
    def _update_cookie_store(response: httpx.Response, url: str, cookie_store: Any) -> None:
        """把响应中的 Set-Cookie 写回 CookieStore。"""
        if cookie_store is None:
            return
        set_cookie = response.headers.get("set-cookie")
        if not set_cookie:
            return
        domain = urlparse(url).netloc
        cookie = SimpleCookie()
        cookie.load(set_cookie)
        cookies: List[Dict[str, str]] = []
        for key in cookie.keys():
            morsel = cookie[key]
            cookies.append({
                "name": morsel.key,
                "value": morsel.value,
                "domain": morsel.get("domain") or domain,
                "path": morsel.get("path") or "/",
            })
        if cookies:
            cookie_store.store(domain, cookies)
            logger.debug(f"HTTP 响应写回 {len(cookies)} 个 Cookie 到 {domain}")
