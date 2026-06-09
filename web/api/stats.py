"""质量概览 API — GET /stats/overview"""

from fastapi import APIRouter

from . import store

router = APIRouter(tags=["stats"])


@router.get("/stats/overview")
def get_overview():
    """获取质量概览指标。对齐 SPEC §5.4 GET /api/v1/stats/overview。"""
    return store.get_stats_overview()
