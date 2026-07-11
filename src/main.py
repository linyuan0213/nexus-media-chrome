"""主FastAPI应用"""

import datetime
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from loguru import logger

from src.api.routes import sessions_router
from src.config.settings import APP_HOST, APP_PORT, APP_VERSION
from src.core.browser_manager import browser_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await browser_manager.start_monitoring()
    try:
        # 触发浏览器预热，失败不影响服务启动
        _ = browser_manager.browser
    except Exception as e:
        logger.warning(f"浏览器预热失败（不影响服务启动）: {e}")
    yield
    await browser_manager.cleanup()


app = FastAPI(
    title="Nexus Media Chrome Server",
    description="Session 隔离的 Chrome 自动化服务器 — 挑战绕过、Cookie 共享、指纹伪装",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.include_router(sessions_router)


@app.get("/")
async def root():
    return {
        "message": "Nexus Media Chrome Server",
        "version": APP_VERSION,
        "docs": "/docs",
        "browser": "ready" if browser_manager.is_alive else "pending",
        "endpoints": {
            "sessions": "POST/GET /sessions",
            "navigate": "POST /sessions/{id}/navigate",
            "html": "GET /sessions/{id}/html",
            "cookies": "GET /sessions/{id}/cookies",
            "click": "POST /sessions/{id}/click",
            "input": "POST /sessions/{id}/input",
            "execute": "POST /sessions/{id}/execute",
            "fetch": "POST /sessions/{id}/fetch",
            "status": "GET /status",
        },
    }


@app.get("/status")
async def status():
    return {
        "status": "running",
        "version": APP_VERSION,
        "browser": "ready" if browser_manager.is_alive else "not_initialized",
        "timestamp": datetime.datetime.now().isoformat(),
    }


def run() -> None:
    """CLI 入口点"""
    uvicorn.run("src.main:app", host=APP_HOST, port=APP_PORT, reload=False)


if __name__ == "__main__":
    run()
