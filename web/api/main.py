"""FastAPI 应用入口。

启动：uvicorn web.api.main:app --reload --port 8010
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 自动加载项目根目录的 .env 文件
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import data_sources, ingestion, map_layers, stats

app = FastAPI(
    title="AeroPulse API",
    description="低空讯图 PoC — 公开低空管控公告的地图化情报工具",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 静态文件 ───
web_dir = Path(__file__).resolve().parent.parent
if web_dir.is_dir():
    app.mount("/web", StaticFiles(directory=str(web_dir), html=True), name="web")

# ─── 路由注册 ───
app.include_router(data_sources.router, prefix="/api/v1")
app.include_router(ingestion.router, prefix="/api/v1")
app.include_router(map_layers.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/web/地图页.html")


@app.get("/api/health")
def health():
    return {"service": "AeroPulse API", "version": "0.1.0", "docs": "/docs"}
