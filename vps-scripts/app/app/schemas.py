from typing import Optional, List
from pydantic import BaseModel


class GroupInfo(BaseModel):
    id: int
    title: str
    username: Optional[str]
    is_megagroup: bool
    is_channel: bool
    member_count: Optional[int] = None


class SendRequest(BaseModel):
    group_ids: List[int]
    message: str
    parse_mode: Optional[str] = "plain"
    disable_web_page_preview: bool = True
    delay_ms: int = 1500


class SendResponse(BaseModel):
    total: int
    success: int
    failed: int


class LogEntry(BaseModel):
    id: int
    group_id: int
    group_title: str
    message_preview: str
    status: str
    error: Optional[str]
    message_id: Optional[int]
    parse_mode: Optional[str]
    created_at: str