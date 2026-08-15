import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class MachineBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    location: str | None = None
    status: str = Field(
        default="operational",
        pattern="^(operational|maintenance|out_of_service)$",
    )
    metadata: dict | None = None


class MachineCreate(MachineBase):
    pass


class MachineUpdate(BaseModel):
    """Actualización parcial de una máquina. Si cambia el texto indexado
    (código, nombre, descripción, ubicación o estado), se re-indexa en FAISS."""
    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    location: str | None = None
    status: str | None = Field(
        default=None, pattern="^(operational|maintenance|out_of_service)$"
    )
    metadata: dict | None = None


class MachineResponse(MachineBase):
    id: int
    created_at: datetime


class MachineUpdateResponse(BaseModel):
    machine: MachineResponse
    reindexed: bool
    num_chunks: int


class WorkOrderCreate(BaseModel):
    machine_id: int
    title: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    status: str = Field(default="open", pattern="^(open|in_progress|completed|cancelled)$")
    assigned_to: str | None = None
    due_date: date | None = None
    metadata: dict | None = None


class WorkOrderUpdate(BaseModel):
    """Actualización parcial de una OT. Si cambia el texto indexado
    (título, descripción, prioridad, estado o máquina), se re-indexa en FAISS."""
    machine_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    priority: str | None = Field(
        default=None, pattern="^(low|medium|high|critical)$"
    )
    status: str | None = Field(
        default=None, pattern="^(open|in_progress|completed|cancelled)$"
    )
    assigned_to: str | None = None
    due_date: date | None = None
    metadata: dict | None = None


class WorkOrderResponse(WorkOrderCreate):
    id: int
    machine_name: str | None = None
    created_at: datetime


class WorkOrderUpdateResponse(BaseModel):
    work_order: WorkOrderResponse
    reindexed: bool
    num_chunks: int


class IngestResponse(BaseModel):
    document_id: uuid.UUID
    document_name: str
    entity_type: str | None = None
    entity_id: int | None = None
    num_chunks: int
    # Blob del archivo original en GCS (None si el storage no está configurado).
    storage_path: str | None = None


class DocumentResponse(BaseModel):
    id: uuid.UUID
    document_name: str
    ref_link: str = ""
    entity_type: str | None = None
    entity_id: int | None = None
    uploaded_by: str | None = None
    storage_path: str | None = None
    created_at: datetime


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


class ReindexRequest(BaseModel):
    """Si space es None, se reconstruyen todos los espacios."""
    space: Literal["machines", "work_orders", "documents"] | None = None


class ReindexResponse(BaseModel):
    spaces: dict[str, int]
