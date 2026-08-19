"""Schemas de ingesta: respuestas de `/ingest` y `/documents`."""

import uuid
from datetime import datetime

from pydantic import BaseModel


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
