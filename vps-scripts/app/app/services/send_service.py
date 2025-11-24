import asyncio
import time
import hashlib
from sqlalchemy.orm import Session
from app.telegram_client import MultiTelegramManager
from app.models import SendLog
from app.config import CONFIG
import random
from app.models import Task, TaskEvent
import json


_SEND_CACHE: dict[str, float] = {}


def _msg_key(account: str, gid: int, message: str, parse_mode: str, disable_web_page_preview: bool) -> str:
    h = hashlib.sha256((parse_mode or "")
                       .encode("utf-8") + b"|" +
                       (b"1" if disable_web_page_preview else b"0") + b"|" +
                       message.encode("utf-8")).hexdigest()[:16]
    return f"{account}:{gid}:{h}"


def _should_skip(account: str, gid: int, message: str, parse_mode: str, disable_web_page_preview: bool, window_s: int = 120) -> bool:
    now = time.monotonic()
    key = _msg_key(account, gid, message, parse_mode, disable_web_page_preview)
    ts = _SEND_CACHE.get(key)
    # prune old
    for k, t in list(_SEND_CACHE.items()):
        if now - t > window_s * 2:
            del _SEND_CACHE[k]
    if ts and (now - ts) < window_s:
        return True
    _SEND_CACHE[key] = now
    return False


async def send_to_groups(
    manager: MultiTelegramManager,
    db: Session,
    account: str,
    group_ids: list[int],
    message: str,
    parse_mode: str,
    disable_web_page_preview: bool,
    delay_ms: int,
    retry_max: int = 0,
    retry_delay_ms: int = 1500,
):
    total = len(group_ids)
    success = 0
    failed = 0
    base_delay_ms = max(delay_ms, 0)
    min_delay_ms = max(getattr(CONFIG, "SEND_MIN_DELAY_MS", 1500), 0)
    jitter_pct = max(0.0, min(getattr(CONFIG, "SEND_JITTER_PCT", 0.15), 0.5))
    base = max(base_delay_ms, min_delay_ms)
    for idx, gid in enumerate(group_ids):
        skipped = _should_skip(account, gid, message, parse_mode, disable_web_page_preview)
        msg_id = None
        err = None
        if skipped:
            status = "skipped"
        else:
            attempt = 0
            ok = False
            while attempt <= max(0, retry_max):
                ok, err, msg_id = await manager.send_message_to_group(
                    account,
                    group_id=gid,
                    text=message,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                )
                if ok:
                    break
                attempt += 1
                if attempt <= retry_max:
                    await asyncio.sleep(max(retry_delay_ms, 0) / 1000.0)
            status = "success" if ok else "failed"
            if status == "success":
                success += 1
            elif status == "failed":
                failed += 1
        preview = message[:200]
        title = str(gid)
        try:
            ent = await manager.get(account).client.get_entity(gid)
            title = getattr(ent, 'title', None) or getattr(ent, 'username', None) or getattr(ent, 'first_name', None) or str(gid)
        except Exception:
            title = str(gid)
        db.add(
            SendLog(
                account_name=account,
                group_id=gid,
                group_title=title,
                message_preview=preview,
                status=status,
                error=None if status == "success" else (err or ("" if status == "skipped" else "send_failed")),
                message_id=msg_id,
                parse_mode=parse_mode,
            )
        )
        db.commit()
        # task progress/heartbeat
        try:
            t = db.query(Task).filter(Task.request_id == request_id).first() if 'request_id' in locals() else None
        except Exception:
            t = None
        if t:
            t.success = success
            t.failed = failed
            t.total = total
            t.current_index = idx + 1
            from datetime import datetime
            t.heartbeat_at = datetime.utcnow()
            db.add(TaskEvent(task_id=t.id, event="progress", detail=f"{t.current_index}/{total}", meta_json=json.dumps({"gid": gid}, ensure_ascii=False)))
            db.commit()
        if base > 0:
            jitter = random.uniform(-jitter_pct, jitter_pct) * base
            wait_ms = max(0.0, base + jitter)
            await asyncio.sleep(wait_ms / 1000.0)
    return {"total": total, "success": success, "failed": failed}