"""Schemas de órdenes de trabajo: lo que la API recibe y devuelve para `/work-orders`."""

from datetime import date, datetime

from pydantic import BaseModel, Field


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
