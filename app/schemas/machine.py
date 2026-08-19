"""Schemas de máquinas: lo que la API recibe y devuelve para `/machines`."""

from datetime import datetime

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
