"""Servicio de preguntas y respuestas.

Flujo: embebe la pregunta -> busca en todos los espacios FAISS (machines,
work_orders, documents) -> fusiona y ordena por similitud coseno (ranking) ->
construye el contexto -> genera la respuesta -> guarda mensajes y citation_logs.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.models import ChatMessage, ChatSession, CitationLog
from ..library import faiss_store
from ..library.embeddings import embeddings, qa_chain


def _search(query_embedding: list[float], k: int, filters: dict | None) -> list[dict]:
    results = faiss_store.search(query_embedding, k=k, filters=filters)
    if settings.min_relevance_score > 0:
        results = [
            r for r in results if r["score"] >= settings.min_relevance_score
        ]
    return results


def answer_question(
    session: Session,
    chat_session: ChatSession,
    question: str,
    top_k: int | None = None,
    filters: dict | None = None,
) -> dict:
    """Procesa una pregunta dentro de una sesión y devuelve la respuesta + fuentes.

    La transacción se confirma aquí; el router hace rollback si algo falla.
    """
    k = top_k or settings.top_k

    user_msg = ChatMessage(session_id=chat_session.id, role="user", content=question)
    session.add(user_msg)
    session.flush()

    # Los filtros explícitos de la petición tienen prioridad sobre el ámbito de
    # la sesión (entity_type/entity_id con los que se creó).
    scope = {}
    if chat_session.entity_type and chat_session.entity_id:
        scope = {
            "entity_type": chat_session.entity_type,
            "entity_id": chat_session.entity_id,
        }
    effective_filters = filters or scope or None

    query_embedding = embeddings.embed_query(question)
    results = _search(query_embedding, k, effective_filters)

    if results:
        context = "\n\n---\n\n".join(
            f"[Fuente: {r['metadata'].get('name') or r['metadata'].get('source')}]\n"
            f"{r['content']}"
            for r in results
        )
    else:
        context = ""

    answer = qa_chain.invoke({"context": context, "question": question})

    assistant_msg = ChatMessage(session_id=chat_session.id, role="assistant", content=answer)
    session.add(assistant_msg)
    session.flush()

    # Citas: qué chunks alimentaron la respuesta y con qué score (ranking).
    for r in results:
        md = r["metadata"]
        session.add(
            CitationLog(
                message_id=assistant_msg.id,
                chunk_id=md.get("chunk_id"),
                entity_type=md.get("entity_type"),
                entity_id=md.get("entity_id"),
                relevance_score=r["score"],
            )
        )

    if not chat_session.title:
        chat_session.title = question[:80]

    session.commit()

    return {
        "message_id": assistant_msg.id,
        "answer": answer,
        "sources": [
            {
                "chunk_id": r["metadata"].get("chunk_id"),
                "source": r["metadata"].get("source"),
                "name": r["metadata"].get("name"),
                "entity_type": r["metadata"].get("entity_type"),
                "entity_id": r["metadata"].get("entity_id"),
                "content": r["content"],
                "score": r["score"],
            }
            for r in results
        ],
    }
