"""Almacén vectorial FAISS con "espacios" por tipo de entidad.

Cada espacio (machines, work_orders, documents) es un índice FAISS separado,
persistido en disco dentro de FAISS_INDEX_DIR/<espacio>/ (index.faiss + index.pkl).

Todos los índices se construyen con normalize_L2=True, es decir, IndexFlatIP
(producto escalar sobre vectores normalizados) -> el score devuelto es la
SIMILITUD COSENO (mayor = más relevante), lo que permite fusionar los
resultados de todos los espacios en un único ranking global.
"""

from __future__ import annotations

import os
import shutil

from langchain_community.vectorstores import FAISS

from ..core.config import settings
from .embeddings import embeddings

_stores: dict[str, FAISS] = {}


def _space_dir(space: str) -> str:
    return os.path.join(settings.faiss_index_dir, space)


def _index_path(space: str) -> str:
    return os.path.join(_space_dir(space), "index.faiss")


def spaces() -> list[str]:
    return list(settings.faiss_spaces)


def get(space: str) -> FAISS | None:
    return _stores.get(space)


def _build_from_db(space: str) -> int:
    """Construye el índice de un espacio desde rag_chunks. Devuelve nº de chunks."""
    from ..core.db import SessionLocal
    from ..core.models import RagChunk

    with SessionLocal() as session:
        chunks = (
            session.query(RagChunk)
            .filter(RagChunk.source_type == space, RagChunk.embedding.isnot(None))
            .order_by(RagChunk.id)
            .all()
        )
    if not chunks:
        return 0

    pairs = [(c.content, c.embedding) for c in chunks]
    metadatas = [_metadata_for_chunk(c) for c in chunks]
    _stores[space] = FAISS.from_embeddings(
        pairs, embeddings, metadatas=metadatas, normalize_L2=True
    )
    save(space)
    return len(chunks)


def init_stores() -> None:
    """Carga los índices desde disco; si faltan, los reconstruye desde la BD."""
    os.makedirs(settings.faiss_index_dir, exist_ok=True)
    for space in spaces():
        if os.path.exists(_index_path(space)):
            _stores[space] = FAISS.load_local(
                _space_dir(space), embeddings, allow_dangerous_deserialization=True
            )
            continue
        _build_from_db(space)


def rebuild(space: str | None = None) -> dict[str, int]:
    """Reconstruye los índices FAISS desde cero (borrando lo actual) a partir de
    rag_chunks. Si `space` es None, reconstruye todos los espacios.
    Devuelve un dict {espacio: nº de chunks indexados}."""
    counts: dict[str, int] = {}
    for sp in (spaces() if space is None else [space]):
        _stores.pop(sp, None)
        shutil.rmtree(_space_dir(sp), ignore_errors=True)
        counts[sp] = _build_from_db(sp)
    return counts


def _metadata_for_chunk(chunk) -> dict:
    return {
        "chunk_id": chunk.id,
        "source": chunk.source_type,
        "entity_type": chunk.entity_type,
        "entity_id": chunk.entity_id,
        "machine_id": chunk.machine_id,
        "work_order_id": chunk.work_order_id,
        "document_id": str(chunk.document_id) if chunk.document_id else None,
        "name": (chunk.metadata_ or {}).get("name"),
    }


def add(
    space: str,
    texts: list[str],
    vectors: list[list[float]],
    metadatas: list[dict],
) -> None:
    """Añade documentos a un espacio y persiste el índice."""
    pairs = list(zip(texts, vectors))
    store = _stores.get(space)
    if store is None:
        store = FAISS.from_embeddings(
            pairs, embeddings, metadatas=metadatas, normalize_L2=True
        )
    else:
        store.add_embeddings(pairs, metadatas=metadatas, normalize_L2=True)
    _stores[space] = store
    save(space)


def save(space: str) -> None:
    os.makedirs(_space_dir(space), exist_ok=True)
    _stores[space].save_local(_space_dir(space))


def delete_by_chunk_ids(space: str, chunk_ids: set[int]) -> None:
    """Elimina del índice FAISS las entradas cuyo metadata.chunk_id esté en chunk_ids.

    LangChain no expone un borrado por metadata, así que recorremos
    index_to_docstore_id buscando los ids FAISS de esos chunks y los borramos.
    """
    store = _stores.get(space)
    if store is None or not chunk_ids:
        return

    # FAISS.delete espera los docstore ids (valores del mapa), no los ids
    # posicionales del índice.
    ids_to_delete = [
        docstore_id
        for docstore_id in store.index_to_docstore_id.values()
        if store.docstore.search(docstore_id).metadata.get("chunk_id") in chunk_ids
    ]
    if ids_to_delete:
        store.delete(ids_to_delete)
        save(space)


def search(
    query_embedding: list[float],
    k: int,
    filters: dict | None = None,
) -> list[dict]:
    """Busca en todos los espacios, fusiona los resultados y ordena por score
    (similitud coseno, descendente). El filtro se aplica sobre el metadata
    (entity_type, entity_id, machine_id, work_order_id...)."""
    results: list[dict] = []
    for space in spaces():
        store = _stores.get(space)
        if store is None:
            continue
        docs = store.similarity_search_with_score_by_vector(
            query_embedding, k=k, filter=filters or None, fetch_k=max(100, k * 10)
        )
        for doc, score in docs:
            results.append(
                {
                    "content": doc.page_content,
                    "score": round(float(score), 4),
                    "metadata": doc.metadata,
                }
            )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:k]
