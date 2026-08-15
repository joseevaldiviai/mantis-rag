import uuid

from fastapi import APIRouter, HTTPException

from ..db import SessionLocal
from ..log import log_event
from ..models import ChatMessage, ChatSession, Machine, WorkOrder
from ..qa_service import answer_question
from ..schemas import (
    ChatMessageRecord,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])


def _validate_entity(session, entity_type: str | None, entity_id: int | None) -> None:
    if entity_type and entity_id:
        model = Machine if entity_type == "machine" else WorkOrder
        if session.get(model, entity_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"No existe la entidad {entity_type} con id {entity_id}.",
            )


@router.post("/sessions", response_model=ChatSessionResponse, status_code=201)
def create_session(payload: ChatSessionCreate):
    """Crea una sesión de chat. Si se indica entity_type/entity_id, las preguntas
    de la sesión se acotarán a esa máquina u orden de trabajo."""
    with SessionLocal() as session:
        _validate_entity(session, payload.entity_type, payload.entity_id)
        chat_session = ChatSession(
            title=payload.title,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
        )
        session.add(chat_session)
        session.commit()
        return ChatSessionResponse(
            id=chat_session.id,
            title=chat_session.title,
            entity_type=chat_session.entity_type,
            entity_id=chat_session.entity_id,
            created_at=chat_session.created_at,
        )


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse)
def send_message(session_id: uuid.UUID, payload: ChatMessageRequest):
    """Hace una pregunta dentro de la sesión: busca en FAISS, genera la respuesta
    y guarda el mensaje del usuario, la respuesta y las citas (citation_logs)."""
    filters = payload.filters.model_dump(exclude_none=True) if payload.filters else None

    with SessionLocal() as session:
        chat_session = session.get(ChatSession, session_id)
        if chat_session is None:
            raise HTTPException(status_code=404, detail="Sesión no encontrada.")

        try:
            result = answer_question(
                session,
                chat_session,
                payload.question,
                top_k=payload.top_k,
                filters=filters,
            )
        except Exception as exc:
            session.rollback()
            log_event(
                "error", "Fallo al responder la pregunta",
                entity_type=chat_session.entity_type,
                entity_id=chat_session.entity_id,
                exc=exc,
            )
            raise HTTPException(
                status_code=500, detail=f"Error generando la respuesta: {exc}"
            ) from exc

        return ChatMessageResponse(**result)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageRecord])
def list_messages(session_id: uuid.UUID):
    with SessionLocal() as session:
        if session.get(ChatSession, session_id) is None:
            raise HTTPException(status_code=404, detail="Sesión no encontrada.")
        messages = (
            session.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id)
            .all()
        )
        return [
            ChatMessageRecord(
                id=m.id, role=m.role, content=m.content, created_at=m.created_at
            )
            for m in messages
        ]
