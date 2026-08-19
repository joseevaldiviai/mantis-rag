"""Contratos Pydantic de la API, organizados por dominio.

Re-exporta los schemas de cada módulo para que los routers importen con:

    from ...schemas import MachineCreate, MachineResponse
"""

from .admin import ReindexRequest, ReindexResponse
from .chat import (
    ChatFilters,
    ChatMessageRecord,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    Source,
)
from .ingest import DocumentResponse, IngestResponse
from .machine import (
    MachineBase,
    MachineCreate,
    MachineResponse,
    MachineUpdate,
    MachineUpdateResponse,
)
from .work_order import (
    WorkOrderCreate,
    WorkOrderResponse,
    WorkOrderUpdate,
    WorkOrderUpdateResponse,
)

__all__ = [
    "ChatFilters",
    "ChatMessageRecord",
    "ChatMessageRequest",
    "ChatMessageResponse",
    "ChatSessionCreate",
    "ChatSessionResponse",
    "DocumentResponse",
    "IngestResponse",
    "MachineBase",
    "MachineCreate",
    "MachineResponse",
    "MachineUpdate",
    "MachineUpdateResponse",
    "ReindexRequest",
    "ReindexResponse",
    "Source",
    "WorkOrderCreate",
    "WorkOrderResponse",
    "WorkOrderUpdate",
    "WorkOrderUpdateResponse",
]
