from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.responses import HTMLResponse, JSONResponse
from starlette.responses import StreamingResponse, Response
from starlette.requests import Request
from app.config import CONFIG
from app.database import Base, engine, SessionLocal
from sqlalchemy import text
from app.telegram_client import multi_manager
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import SendLog, Task, TaskEvent
from app.services.send_service import send_to_groups
from app.services.group_service import get_groups
from app.services.group_service import clear_group_cache
import time
import uuid
import asyncio
import uuid
import asyncio

app = Starlette()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def admin_token_middleware(request, call_next):
    token = request.headers.get("X-Admin-Token")
    request.state.admin_token = token
    response = await call_next(request)
    return response


@app.route("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.route("/api/accounts")
async def list_accounts(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return JSONResponse(list(CONFIG.ACCOUNTS.keys()))

@app.route("/api/accounts/status")
async def list_accounts_status(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    names = list(CONFIG.ACCOUNTS.keys())
    data = []
    for name in names:
        try:
            authorized = await multi_manager.is_authorized(name)
        except Exception:
            authorized = False
        data.append({"account": name, "authorized": authorized})
    return JSONResponse(data)

@app.route("/api/groups")
async def list_groups(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    only_groups = request.query_params.get("only_groups", "true").lower() != "false"
    account = request.query_params.get("account") or CONFIG.DEFAULT_ACCOUNT
    refresh = request.query_params.get("refresh", "false").lower() in ("1", "true", "yes")
    if getattr(CONFIG, "GROUP_CACHE_ENABLED", 1) == 0:
        refresh = True
    db: Session = SessionLocal()
    try:
        data = await get_groups(multi_manager, account=account, only_groups=only_groups, refresh=refresh, db=db)
        return JSONResponse(data)
    except BaseException as e:
        msg = str(e).lower()
        if "not authorized" in msg or "session" in msg:
            return JSONResponse({"detail": "session_not_authorized"}, status_code=403)
        return JSONResponse({"detail": "internal_error"}, status_code=500)
    finally:
        db.close()

@app.route("/api/groups/cache/clear")
async def clear_groups_cache(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    account = request.query_params.get("account")
    only_groups_param = request.query_params.get("only_groups")
    only_groups = None
    if only_groups_param is not None:
        only_groups = only_groups_param.lower() != "false"
    db: Session = SessionLocal()
    try:
        resp = clear_group_cache(account=account, only_groups=only_groups, db=db)
        return JSONResponse({"ok": True, **resp})
    finally:
        db.close()


@app.route("/api/send", methods=["POST"])
async def send(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    body = await request.json()
    group_ids = body.get("group_ids") or []
    message = (body.get("message") or "").strip()
    parse_mode = body.get("parse_mode") or "plain"
    disable_web_page_preview = bool(body.get("disable_web_page_preview", True))
    delay_ms = int(body.get("delay_ms", 1500))
    delay_ms = max(delay_ms, getattr(CONFIG, "SEND_MIN_DELAY_MS", 1500))
    retry_max = int(body.get("retry_max", getattr(CONFIG, "SEND_RETRY_MAX", 0)))
    retry_delay_ms = int(body.get("retry_delay_ms", getattr(CONFIG, "SEND_RETRY_DELAY_MS", 1500)))
    account = body.get("account") or CONFIG.DEFAULT_ACCOUNT
    request_id = body.get("request_id")
    ok, reason = _check_request_guard(token, request_id)
    if not ok:
        return JSONResponse({"detail": "Too Many Requests"}, status_code=429, headers={"Retry-After": "1"})
    if not group_ids or not message:
        return JSONResponse({"detail": "group_ids and message required"}, status_code=400)
    db: Session = SessionLocal()
    try:
        resp = await send_to_groups(multi_manager, db, account, group_ids, message, parse_mode, disable_web_page_preview, delay_ms, retry_max, retry_delay_ms)
        return JSONResponse(resp)
    finally:
        db.close()


@app.route("/api/test-send", methods=["POST"])
async def test_send(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    body = await request.json()
    group_ids = body.get("group_ids") or []
    message = (body.get("message") or "").strip()
    parse_mode = body.get("parse_mode") or "plain"
    disable_web_page_preview = bool(body.get("disable_web_page_preview", True))
    account = body.get("account") or CONFIG.DEFAULT_ACCOUNT
    retry_max = int(body.get("retry_max", getattr(CONFIG, "SEND_RETRY_MAX", 0)))
    retry_delay_ms = int(body.get("retry_delay_ms", getattr(CONFIG, "SEND_RETRY_DELAY_MS", 1500)))
    request_id = body.get("request_id")
    ok, reason = _check_request_guard(token, request_id)
    if not ok:
        return JSONResponse({"detail": "Too Many Requests"}, status_code=429, headers={"Retry-After": "1"})
    if not group_ids or not message:
        return JSONResponse({"detail": "group_ids and message required"}, status_code=400)
    db: Session = SessionLocal()
    try:
        resp = await send_to_groups(multi_manager, db, account, group_ids, message, parse_mode, disable_web_page_preview, 0, retry_max, retry_delay_ms)
        return JSONResponse(resp)
    finally:
        db.close()


@app.route("/api/logs")
async def recent_logs(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    limit = int(request.query_params.get("limit", 50))
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(SendLog)
            .order_by(SendLog.created_at.desc())
            .limit(limit)
            .all()
        )
        data = [
            {
                "id": r.id,
                "group_id": r.group_id,
                "group_title": r.group_title,
                "message_preview": r.message_preview,
                "status": r.status,
                "error": r.error,
                "message_id": getattr(r, "message_id", None),
                "parse_mode": getattr(r, "parse_mode", None),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
        return JSONResponse(data)
    finally:
        db.close()


@app.route("/api/logs/export.csv")
async def export_logs_csv(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    limit = int(request.query_params.get("limit", 1000))
    status_filter = request.query_params.get("status")
    db: Session = SessionLocal()
    try:
        q = db.query(SendLog).order_by(SendLog.created_at.desc())
        if status_filter:
            q = q.filter(SendLog.status == status_filter)
        rows = q.limit(limit).all()
        import csv
        from io import StringIO
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id","account_name","group_id","group_title","message_preview","status","error","message_id","parse_mode","created_at"])
        for r in rows:
            writer.writerow([
                r.id,
                r.account_name,
                r.group_id,
                r.group_title,
                (r.message_preview or "").replace("\n"," ").strip(),
                r.status,
                (r.error or "").replace("\n"," ").strip(),
                getattr(r, "message_id", None),
                getattr(r, "parse_mode", None),
                r.created_at.isoformat() if r.created_at else "",
            ])
        csv_data = buf.getvalue()
        headers = {"Content-Type": "text/csv; charset=utf-8", "Content-Disposition": "attachment; filename=send_logs.csv"}
        return Response(content=csv_data, media_type="text/csv", headers=headers)
    finally:
        db.close()


async def startup_event():
    Base.metadata.create_all(bind=engine)
    pass
    try:
        with engine.connect() as conn:
            cols = conn.execute(text("PRAGMA table_info('send_logs')")).fetchall()
            names = {c[1] for c in cols}
            if 'account_name' not in names:
                conn.execute(text("ALTER TABLE send_logs ADD COLUMN account_name VARCHAR(64)"))
                conn.commit()
            if 'message_id' not in names:
                conn.execute(text("ALTER TABLE send_logs ADD COLUMN message_id INTEGER"))
                conn.commit()
            if 'parse_mode' not in names:
                conn.execute(text("ALTER TABLE send_logs ADD COLUMN parse_mode VARCHAR(16)"))
                conn.commit()
    except Exception:
        pass
    # restart running tasks
    db: Session = SessionLocal()
    try:
        rows = db.query(Task).filter(Task.status == "running").limit(100).all()
        for t in rows:
            try:
                gids = json.loads(t.group_ids_json or "[]")
                # resume from current_index
                start_idx = max(0, (t.current_index or 0))
                rem = gids[start_idx:]
                if rem:
                    asyncio.create_task(_run_send_task(t.id, t.account_name, rem, t.message, t.parse_mode, bool(t.disable_web_page_preview), t.delay_ms))
            except Exception:
                pass
    finally:
        db.close()


_REQ_IDS: dict[str, float] = {}
_LAST_TS: dict[str, float] = {}


def _check_request_guard(token: str, request_id: str | None, window_ms: int = 500):
    now = time.monotonic()
    # prune old ids
    for k, ts in list(_REQ_IDS.items()):
        if now - ts > 60:
            del _REQ_IDS[k]
    # duplicate id guard
    if request_id:
        if request_id in _REQ_IDS:
            return False, "duplicate"
        _REQ_IDS[request_id] = now
    # throttle by token
    last = _LAST_TS.get(token, 0.0)
    if now - last < (window_ms / 1000.0):
        _LAST_TS[token] = now
        return False, "too_frequent"
    _LAST_TS[token] = now
    return True, None

app.add_event_handler("startup", startup_event)

TASKS: dict[str, dict] = {}


@app.route("/api/send-async", methods=["POST"])
async def send_async(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    body = await request.json()
    group_ids = body.get("group_ids") or []
    message = (body.get("message") or "").strip()
    parse_mode = body.get("parse_mode") or "plain"
    disable_web_page_preview = bool(body.get("disable_web_page_preview", True))
    delay_ms = int(body.get("delay_ms", 1500))
    delay_ms = max(delay_ms, getattr(CONFIG, "SEND_MIN_DELAY_MS", 1500))
    account = body.get("account") or CONFIG.DEFAULT_ACCOUNT
    request_id = body.get("request_id")
    ok, reason = _check_request_guard(token, request_id)
    if not ok:
        return JSONResponse({"detail": "Too Many Requests"}, status_code=429, headers={"Retry-After": "1"})
    if not group_ids or not message:
        return JSONResponse({"detail": "group_ids and message required"}, status_code=400)
    task_id = uuid.uuid4().hex[:24]
    db: Session = SessionLocal()
    try:
        t = Task(
            id=task_id,
            status="running",
            total=len(group_ids),
            success=0,
            failed=0,
            account_name=account,
            message=message,
            parse_mode=parse_mode,
            disable_web_page_preview=1 if disable_web_page_preview else 0,
            delay_ms=delay_ms,
            current_index=0,
            group_ids_json=json.dumps(group_ids),
            request_id=request_id,
        )
        db.add(t)
        db.add(TaskEvent(task_id=task_id, event="created", detail="task_created", meta_json=json.dumps({"count": len(group_ids)}, ensure_ascii=False)))
        db.commit()
    finally:
        db.close()
    asyncio.create_task(_run_send_task(task_id, account, group_ids, message, parse_mode, disable_web_page_preview, delay_ms))
    return JSONResponse({"task_id": task_id})


@app.route("/api/task-status")
async def task_status(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    task_id = request.query_params.get("task_id")
    if not task_id:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    db: Session = SessionLocal()
    try:
        t = db.query(Task).filter(Task.id == task_id).first()
        if not t:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        data = {
            "task_id": t.id,
            "status": t.status,
            "total": t.total,
            "success": t.success,
            "failed": t.failed,
            "current_index": t.current_index,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        }
        return JSONResponse(data)
    finally:
        db.close()


async def _run_send_task(task_id: str, account: str, group_ids: list[int], message: str, parse_mode: str, disable_web_page_preview: bool, delay_ms: int):
    db: Session = SessionLocal()
    try:
        delay = max(delay_ms, 0) / 1000.0
        succ = 0
        fail = 0
        for gid in group_ids:
            # pause/stop checks
            try:
                t = db.query(Task).filter(Task.id == task_id).first()
                if t and t.stop_requested:
                    from datetime import datetime
                    t.status = "stopped"
                    t.finished_at = datetime.utcnow()
                    db.add(TaskEvent(task_id=task_id, event="stopped", detail="task_stopped", meta_json=json.dumps({}, ensure_ascii=False)))
                    db.commit()
                    break
                while t and t.paused:
                    await asyncio.sleep(1)
                    t = db.query(Task).filter(Task.id == task_id).first()
            except Exception:
                pass
            ok, err, msg_id = await multi_manager.send_message_to_group(
                account,
                group_id=gid,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
            status = "success" if ok else "failed"
            if ok:
                succ += 1
            else:
                fail += 1
            preview = message[:200]
            title = str(gid)
            try:
                ent = await multi_manager.get(account).client.get_entity(gid)
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
                    error=None if ok else (err or "send_failed"),
                    message_id=msg_id,
                    parse_mode=parse_mode,
                )
            )
            db.commit()
            try:
                from datetime import datetime
                t = db.query(Task).filter(Task.id == task_id).first()
                if t:
                    t.success = succ
                    t.failed = fail
                    t.current_index = (t.current_index or 0) + 1
                    t.heartbeat_at = datetime.utcnow()
                    db.add(TaskEvent(task_id=task_id, event="progress", detail=f"{t.current_index}/{t.total}", meta_json=json.dumps({"gid": gid}, ensure_ascii=False)))
                    db.commit()
            except Exception:
                pass
            if delay > 0:
                await asyncio.sleep(delay)
        try:
            from datetime import datetime
            t = db.query(Task).filter(Task.id == task_id).first()
            if t:
                if t.status not in ("stopped", "error"):
                    t.status = "done"
                t.finished_at = datetime.utcnow()
                db.add(TaskEvent(task_id=task_id, event="finished", detail="task_done", meta_json=json.dumps({}, ensure_ascii=False)))
                db.commit()
        except Exception:
            pass
    except Exception:
        try:
            from datetime import datetime
            t = db.query(Task).filter(Task.id == task_id).first()
            if t:
                t.status = "error"
                t.finished_at = datetime.utcnow()
                db.add(TaskEvent(task_id=task_id, event="error", detail="task_error", meta_json=json.dumps({}, ensure_ascii=False)))
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
@app.route("/api/login/send-code", methods=["POST"])
async def login_send_code(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    body = await request.json()
    account = body.get("account") or CONFIG.DEFAULT_ACCOUNT
    phone = (body.get("phone") or "").strip()
    force_sms = bool(body.get("force_sms", False))
    if not phone:
        return JSONResponse({"detail": "phone required"}, status_code=400)
    data = await multi_manager.send_login_code(account, phone, force_sms)
    if data.get("ok"):
        return JSONResponse({"ok": True})
    if "retry_after" in data:
        return JSONResponse({"detail": "flood_wait", "retry_after": data["retry_after"]}, status_code=429)
    return JSONResponse({"detail": data.get("error", "send_failed")}, status_code=400)

@app.route("/api/login/confirm", methods=["POST"])
async def login_confirm(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    body = await request.json()
    account = body.get("account") or CONFIG.DEFAULT_ACCOUNT
    phone = (body.get("phone") or "").strip()
    code = (body.get("code") or "").strip()
    password = body.get("password") or None
    if not phone or not code:
        return JSONResponse({"detail": "phone and code required"}, status_code=400)
    data = await multi_manager.confirm_login(account, phone, code, password)
    return JSONResponse({"ok": True, "user": data})

@app.route("/api/account-status")
async def account_status(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    account = request.query_params.get("account") or CONFIG.DEFAULT_ACCOUNT
    try:
        authorized = await multi_manager.is_authorized(account)
    except Exception:
        authorized = False
    return JSONResponse({"account": account, "authorized": authorized})
@app.route("/api/tasks")
async def list_tasks(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    db: Session = SessionLocal()
    try:
        rows = db.query(Task).order_by(Task.started_at.desc()).limit(100).all()
        data = [
            {
                "task_id": r.id,
                "status": r.status,
                "total": r.total,
                "success": r.success,
                "failed": r.failed,
                "current_index": r.current_index,
                "account": r.account_name,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]
        return JSONResponse(data)
    finally:
        db.close()

@app.route("/api/task-events")
async def task_events(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    task_id = request.query_params.get("task_id")
    page = int(request.query_params.get("page", 1))
    size = int(request.query_params.get("size", 50))
    if not task_id:
        return JSONResponse({"detail": "task_id required"}, status_code=400)
    db: Session = SessionLocal()
    try:
        q = db.query(TaskEvent).filter(TaskEvent.task_id == task_id).order_by(TaskEvent.ts.desc())
        rows = q.offset((page - 1) * size).limit(size).all()
        data = [
            {
                "id": r.id,
                "task_id": r.task_id,
                "ts": r.ts.isoformat() if r.ts else None,
                "event": r.event,
                "detail": r.detail,
                "meta_json": r.meta_json,
            }
            for r in rows
        ]
        return JSONResponse({"page": page, "size": size, "items": data})
    finally:
        db.close()
@app.route("/api/task-control", methods=["POST"])
async def task_control(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != CONFIG.ADMIN_TOKEN:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    body = await request.json()
    task_id = body.get("task_id")
    action = body.get("action")  # pause | resume | stop
    if not task_id or action not in ("pause", "resume", "stop"):
        return JSONResponse({"detail": "bad_request"}, status_code=400)
    db: Session = SessionLocal()
    try:
        t = db.query(Task).filter(Task.id == task_id).first()
        if not t:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        from datetime import datetime
        if action == "pause":
            t.paused = 1
            db.add(TaskEvent(task_id=task_id, event="paused", detail="task_paused", meta_json=json.dumps({}, ensure_ascii=False)))
        elif action == "resume":
            t.paused = 0
            db.add(TaskEvent(task_id=task_id, event="resumed", detail="task_resumed", meta_json=json.dumps({}, ensure_ascii=False)))
        elif action == "stop":
            t.stop_requested = 1
            db.add(TaskEvent(task_id=task_id, event="stop_requested", detail="task_stop_requested", meta_json=json.dumps({}, ensure_ascii=False)))
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()