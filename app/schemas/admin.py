"""Schemas de administración: endpoint `/reindex`."""

from typing import Literal

from pydantic import BaseModel


class ReindexRequest(BaseModel):
    """Si space es None, se reconstruyen todos los espacios."""

    space: Literal["machines", "work_orders", "documents"] | None = None


class ReindexResponse(BaseModel):
    spaces: dict[str, int]
