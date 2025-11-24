from fastapi import APIRouter, HTTPException, Depends
from starlette.requests import Request
from sqlalchemy.orm import Session
from app.config import CONFIG
from app.database import get_db
from app.schemas import SendRequest, SendResponse
from app.services.send_service import send_to_groups
from app.telegram_client import tg_manager


router = APIRouter()


@router.post("/send", response_model=SendResponse)
async def send(request: Request, body: SendRequest, db: Session = Depends(get_db)):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not body.group_ids or not body.message.strip():
        raise HTTPException(status_code=400, detail="group_ids and message required")
    return await send_to_groups(tg_manager, db, body)


@router.post("/test-send", response_model=SendResponse)
async def test_send(request: Request, body: SendRequest, db: Session = Depends(get_db)):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not body.group_ids or not body.message.strip():
        raise HTTPException(status_code=400, detail="group_ids and message required")
    body.delay_ms = 0
    return await send_to_groups(tg_manager, db, body)