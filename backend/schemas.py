"""Pydantic contracts for the Poka API (v1)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    upload_ids: List[str] = Field(default_factory=list, max_length=5)
    project_id: Optional[str] = None
    deep_mode: bool = False
    force_search: bool = False
    active_tier: Optional[str] = None


class ChatMessage(BaseModel):
    message: Dict[str, Any]
    active_tier: str = ""
    task_type: str = ""


class RegenerateRequest(BaseModel):
    index: int
    project_id: Optional[str] = None
    deep_mode: bool = False
    force_search: bool = False
    active_tier: Optional[str] = None


class SendResponse(BaseModel):
    message: Dict[str, Any]
    active_tier: str = ""
    task_type: str = ""
    warnings: List[str] = Field(default_factory=list)


class ChatsResponse(BaseModel):
    chats: List[Dict[str, Any]]
    current: List[Dict[str, Any]]


class ArchiveRequest(BaseModel):
    project_id: Optional[str] = None
    chat_id: Optional[str] = None


class OpenChatRequest(BaseModel):
    id: str

class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class TruncateRequest(BaseModel):
    index: int = Field(ge=0)


class UploadMeta(BaseModel):
    id: str
    kind: str
    name: str


class ArtifactMeta(BaseModel):
    id: str
    kind: str
    name: str
    sub: str = ""


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ProjectRename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class TextBody(BaseModel):
    text: str = ""


class BriefFromMessage(BaseModel):
    index: int
    project_id: Optional[str] = None


class HealthResponse(BaseModel):
    ok: bool = True
    tiers: List[str] = Field(default_factory=list)
    auth_mode: str = "open"
