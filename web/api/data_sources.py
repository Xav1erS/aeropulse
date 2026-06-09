"""数据源 API — GET/PATCH/POST crawl"""

from fastapi import APIRouter, HTTPException, Query

from . import store

router = APIRouter(tags=["data-sources"])


@router.get("/data-sources")
def list_sources(
    province: str | None = Query(None),
    source_level: str | None = Query(None),
    enabled: bool | None = Query(None),
):
    items = store.list_data_sources(province=province, source_level=source_level, enabled=enabled)
    return {"items": items, "total": len(items)}


@router.patch("/data-sources/{source_id}")
def patch_source(source_id: str, body: dict):
    result = store.update_data_source(source_id, body)
    if not result:
        raise HTTPException(404, "数据源不存在")
    return result


@router.post("/data-sources")
def create_source(body: dict):
    if not body.get("source_name") or not body.get("source_url"):
        raise HTTPException(400, "source_name 和 source_url 为必填")
    return store.create_data_source(body)


@router.post("/data-sources/{source_id}/crawl")
def trigger_crawl(source_id: str):
    src = store.get_data_source(source_id)
    if not src:
        raise HTTPException(404, "数据源不存在")
    # PoC 阶段：标记为采集已触发（实际采集由 source_audit 执行）
    store.update_data_source(source_id, {
        "last_crawl_status": "running",
    })
    return {
        "task_id": f"crawl_{source_id}",
        "status": "running",
        "message": f"已触发数据源 [{src['source_name']}] 采集任务",
    }
