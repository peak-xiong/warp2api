from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse, RedirectResponse

from warp2api.api.admin_auth import require_admin_auth
from warp2api.application.services.token_pool_service import get_token_pool_service

router = APIRouter()
ADMIN_API_PREFIX = "/admin/api/tokens"


class BatchImportRequest(BaseModel):
    tokens: List[str] = Field(default_factory=list)


class AddTokenRequest(BaseModel):
    token: str


class UpdateTokenRequest(BaseModel):
    label: Optional[str] = None
    status: Optional[str] = None


@router.get("/admin/tokens", response_class=HTMLResponse)
async def admin_tokens_page():
    file_path = Path("static") / "admin_tokens.html"
    if not file_path.exists():
        return HTMLResponse("admin_tokens.html not found", status_code=404)
    return HTMLResponse(file_path.read_text(encoding="utf-8"))


@router.get("/admin/tokens/ui")
async def admin_tokens_ui_redirect():
    return RedirectResponse(url="/admin/tokens", status_code=307)


@router.get(f"{ADMIN_API_PREFIX}")
async def admin_list_tokens(request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    return {"success": True, "data": svc.list_tokens()}


@router.post(f"{ADMIN_API_PREFIX}")
async def admin_add_token(payload: AddTokenRequest, request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    actor = request.headers.get("x-admin-actor") or "admin"
    result = svc.add_token(payload.token, actor=actor)
    return {"success": True, "data": result}


@router.post(f"{ADMIN_API_PREFIX}/batch-import")
async def admin_batch_import_tokens(payload: BatchImportRequest, request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    actor = request.headers.get("x-admin-actor") or "admin"
    result = svc.batch_import(payload.tokens, actor=actor)
    return {"success": True, "data": result}


@router.patch(f"{ADMIN_API_PREFIX}" + "/{token_id}")
async def admin_update_token(token_id: int, payload: UpdateTokenRequest, request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    actor = request.headers.get("x-admin-actor") or "admin"
    try:
        data = svc.update_token(token_id, label=payload.label, status=payload.status, actor=actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"success": True, "data": data}


@router.post(f"{ADMIN_API_PREFIX}" + "/{token_id}/refresh")
async def admin_refresh_token(token_id: int, request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    actor = request.headers.get("x-admin-actor") or "admin"
    try:
        result = await svc.refresh_token(token_id, actor=actor)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"success": True, "data": result}


@router.post(f"{ADMIN_API_PREFIX}" + "/{token_id}/health-check")
async def admin_health_check_token(token_id: int, request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    actor = request.headers.get("x-admin-actor") or "admin"
    try:
        result = await svc.health_check_token(token_id, actor=actor)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"success": True, "data": result}


@router.post(f"{ADMIN_API_PREFIX}/refresh-all")
async def admin_refresh_all_tokens(request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    actor = request.headers.get("x-admin-actor") or "admin"
    result = await svc.refresh_all(actor=actor)
    return {"success": True, "data": result}


@router.get(f"{ADMIN_API_PREFIX}/statistics")
async def admin_tokens_statistics(request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    return {"success": True, "data": svc.statistics()}


@router.get(f"{ADMIN_API_PREFIX}/events")
async def admin_tokens_events(request: Request, limit: int = Query(100, ge=1, le=500)):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    return {"success": True, "data": svc.events(limit=limit)}


@router.get(f"{ADMIN_API_PREFIX}/health")
async def admin_tokens_health(request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    return {"success": True, "data": svc.health()}


@router.get(f"{ADMIN_API_PREFIX}/readiness")
async def admin_tokens_readiness(request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    return {"success": True, "data": svc.readiness()}


@router.get(f"{ADMIN_API_PREFIX}" + "/{token_id}")
async def admin_get_token(token_id: int, request: Request):
    await require_admin_auth(request)
    svc = get_token_pool_service()
    token = svc.get_token(token_id)
    if not token:
        raise HTTPException(404, "token not found")
    return {"success": True, "data": token}
