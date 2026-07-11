"""Nexus Media Chrome Server 入口点"""
import uvicorn

if __name__ == "__main__":
    from src.config.settings import APP_HOST, APP_PORT
    
    uvicorn.run("src.main:app", host=APP_HOST, port=APP_PORT, reload=False)
