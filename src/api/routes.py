"""API 路由 — Session 为操作单元。"""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.api.schemas import (
    ApiResponse,
    ClickRequest,
    CreateSessionRequest,
    ExecuteRequest,
    HttpFetchRequest,
    InputRequest,
    NavigateRequest,
    RequestOperation,
)
from src.config.settings import HTTP_CLIENT_TIMEOUT, HTTP_MAX_REDIRECTS
from src.core.browser_manager import browser_manager
from src.core.session import SessionManager, session_manager
from src.http.client import HttpClient

sessions_router = APIRouter(prefix="/sessions", tags=["sessions"])


def _get_sm() -> SessionManager:
    global session_manager
    if session_manager is None:
        session_manager = SessionManager(browser_manager.browser)
    return session_manager


@sessions_router.post("", response_model=ApiResponse)
async def create_session(request: CreateSessionRequest):
    sm = _get_sm()
    try:
        session = await asyncio.to_thread(
            sm.create,
            request.session_id,
            request.fingerprint_profile,
            request.user_agent,
            request.proxy,
        )
        return ApiResponse(code=0, message="会话已创建", data=session.to_dict())
    except ValueError as e:
        # 已存在则直接返回现有会话
        if "已存在" in str(e):
            session = sm.get(request.session_id)
            return ApiResponse(code=0, message="会话已存在", data=session.to_dict())
        raise HTTPException(status_code=409, detail=str(e))


@sessions_router.get("", response_model=ApiResponse)
async def list_sessions():
    sm = _get_sm()
    return ApiResponse(code=0, message="ok", data={"sessions": sm.list_all()})


@sessions_router.delete("/{session_id}", response_model=ApiResponse)
async def delete_session(session_id: str):
    try:
        sm = _get_sm()
        await asyncio.to_thread(sm.delete, session_id)
        return ApiResponse(code=0, message=f"会话 {session_id} 已删除", data=None)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@sessions_router.post("/{session_id}/navigate", response_model=ApiResponse)
async def navigate(session_id: str, request: NavigateRequest):
    try:
        sm = _get_sm()
        session = sm.get(session_id)
        result = await asyncio.to_thread(
            session.navigate,
            request.url,
            request.tab_name,
            request.cookie,
            request.referer,
            request.timeout,
        )
        return ApiResponse(code=0, message="ok", data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@sessions_router.get("/{session_id}/html", response_model=ApiResponse)
async def get_html(session_id: str):
    try:
        sm = _get_sm()
        session = sm.get(session_id)
        result = await asyncio.to_thread(session.get_html)
        return ApiResponse(code=0, message="ok", data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@sessions_router.get("/{session_id}/cookies", response_model=ApiResponse)
async def get_cookies(session_id: str, domain: str = Query(None)):
    try:
        sm = _get_sm()
        session = sm.get(session_id)
        result = session.get_cookies(domain)
        return ApiResponse(code=0, message="ok", data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@sessions_router.post("/{session_id}/click", response_model=ApiResponse)
async def click(session_id: str, request: ClickRequest):
    try:
        sm = _get_sm()
        session = sm.get(session_id)
        await asyncio.to_thread(session.click, request.selector)
        return ApiResponse(code=0, message=f"已点击: {request.selector}", data=None)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@sessions_router.post("/{session_id}/input", response_model=ApiResponse)
async def input_text(session_id: str, request: InputRequest):
    try:
        sm = _get_sm()
        session = sm.get(session_id)
        await asyncio.to_thread(session.input_text, request.selector, request.text)
        return ApiResponse(code=0, message=f"已输入: {request.text}", data=None)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@sessions_router.post("/{session_id}/execute", response_model=ApiResponse)
async def execute_js(session_id: str, request: ExecuteRequest):
    try:
        sm = _get_sm()
        session = sm.get(session_id)
        result = await asyncio.to_thread(session.execute, request.script)
        return ApiResponse(code=0, message="ok", data={"result": result})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@sessions_router.post("/{session_id}/fetch", response_model=ApiResponse)
async def http_fetch(session_id: str, request: HttpFetchRequest):
    try:
        sm = _get_sm()
        session = sm.get(session_id)
        client = HttpClient(
            base_timeout=HTTP_CLIENT_TIMEOUT,
            max_redirects=HTTP_MAX_REDIRECTS,
        )
        result = await asyncio.to_thread(
            client.fetch,
            url=request.url,
            method=request.method,
            headers=request.headers,
            data=request.data,
            cookie_store=session.cookie_store,
            timeout=request.timeout,
        )
        return ApiResponse(code=0, message="ok", data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


_CHALLENGE_STATUS_CODES = {403, 503, 429}
_CHALLENGE_INDICATORS = [
    "Just a moment",
    "cf-turnstile-response",
    "Checking your browser",
    "DDoS protection",
    "challenge",
    "cf-challenge",
    "please wait",
]


def _is_challenge_response(result: dict[str, Any]) -> bool:
    """判断 fetch 结果是否命中 WAF/盾。"""
    if result.get("status_code") in _CHALLENGE_STATUS_CODES:
        return True
    body = (result.get("body") or "").lower()
    return any(indicator.lower() in body for indicator in _CHALLENGE_INDICATORS)


def _clean_response_headers(headers: dict[str, str]) -> dict[str, str]:
    """移除 body 已解码后不再适用的压缩相关头，避免下游重复解码。"""
    cleaned = dict(headers)
    for key in list(cleaned.keys()):
        if key.lower() in ("content-encoding", "transfer-encoding"):
            cleaned.pop(key)
    return cleaned


@sessions_router.post("/{session_id}/request", response_model=ApiResponse)
async def unified_request(session_id: str, request: RequestOperation):
    """聚合请求：fetch 优先；命中挑战且允许时改用浏览器网络栈或 navigate 过盾后再 fetch。"""
    try:
        sm = _get_sm()
        session = sm.get(session_id)
        client = HttpClient(
            base_timeout=HTTP_CLIENT_TIMEOUT,
            max_redirects=HTTP_MAX_REDIRECTS,
        )

        if request.return_html:
            # 渲染模式：直接 navigate 取 HTML
            result = await asyncio.to_thread(
                session.navigate,
                request.url,
                None,
                request.cookie,
                None,
                request.timeout,
            )
            return ApiResponse(
                code=0,
                message="ok",
                data={
                    "status_code": 200,
                    "headers": {"content-type": "text/html; charset=utf-8"},
                    "body": "",
                    "html": result.get("html", ""),
                    "challenge": result.get("challenge"),
                    "url": result.get("url", request.url),
                },
            )

        fetch_headers = dict(request.headers or {})
        if request.cookie:
            fetch_headers["Cookie"] = request.cookie

        # HTTP 模式：先 fetch
        result = await asyncio.to_thread(
            client.fetch,
            url=request.url,
            method=request.method,
            headers=fetch_headers,
            data=request.data,
            cookie_store=session.cookie_store,
            timeout=request.timeout,
        )

        # 命中挑战且允许回退时过盾
        if _is_challenge_response(result) and request.navigate_if_challenge:
            if request.browser_fetch_on_challenge:
                # 使用浏览器网络栈重新请求，获取原始响应体
                result = await asyncio.to_thread(
                    session.browser_fetch,
                    request.url,
                    request.method,
                    fetch_headers,
                    request.data,
                    request.cookie,
                    request.timeout,
                )
            else:
                nav_result = await asyncio.to_thread(
                    session.navigate,
                    request.url,
                    None,
                    request.cookie,
                    None,
                    request.timeout,
                )
                # 过盾后再 fetch 一次
                result = await asyncio.to_thread(
                    client.fetch,
                    url=request.url,
                    method=request.method,
                    headers=fetch_headers,
                    data=request.data,
                    cookie_store=session.cookie_store,
                    timeout=request.timeout,
                )
                result["challenge"] = nav_result.get("challenge")
                result["url_after_challenge"] = nav_result.get("url", request.url)

        result["headers"] = _clean_response_headers(result.get("headers", {}))
        return ApiResponse(code=0, message="ok", data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
