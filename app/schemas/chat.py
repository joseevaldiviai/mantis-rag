"""Schemas de chat: sesiones, mensajes, filtros y fuentes citadas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    title: str | None = None
    entity_type: Literal["machine", "work_order"] | None = None
    entity_id: int | None = None


class ChatSessionResponse(ChatSessionCreate):
    id: uuid.UUID
    created_at: datetime


class ChatFilters(BaseModel):
    entity_type: Literal["machine", "work_order"] | None = None
    entity_id: int | None = None
    machine_id: int | None = None
    work_order_id: int | None = None


class ChatMessageRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    filters: ChatFilters | None = None


class Source(BaseModel):
    chunk_id: int
    source: str
    name: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    content: str
    score: float


class ChatMessageResponse(BaseModel):
    message_id: int
    answer: str
    sources: list[Source] = []


class ChatMessageRecord(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
