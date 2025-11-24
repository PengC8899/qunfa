from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from app.config import CONFIG
from app.schemas import GroupInfo
from app.telegram_client import tg_manager
from app.services.group_service import get_groups


router = APIRouter()


@router.get("/groups", response_model=list[GroupInfo])
async def list_groups(request: Request, only_groups: bool = True, refresh: bool = False):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await get_groups(tg_manager, only_groups=only_groups)