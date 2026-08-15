"""Indexación orientada al CMMS.

Cada máquina, orden de trabajo y documento se convierte en chunks con un texto
contextual (incluye código, estado, prioridad…) para que los embeddings capturen
el dominio de mantenimiento. El texto + metadata se guardan en rag_chunks y el
vector en el espacio FAISS correspondiente.

También incluye el re-indexado automático: al actualizar una entidad se compara
el texto indexado con el nuevo; si cambió, se borran los chunks viejos
(FAISS + BD) y se indexan de nuevo.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from . import faiss_store
from .config import settings
from .embeddings import embeddings
from .models import Document, Machine, RagChunk, WorkOrder


# ---------------------------------------------------------------------------
# Texto indexado (el texto que se embebe)
# ---------------------------------------------------------------------------

def machine_index_text(machine: Machine) -> str:
    parts = [f"MAQUINARIA: {machine.name} (código: {machine.code})"]
    if machine.location:
        parts.append(f"Ubicación: {machine.location}")
    parts.append(f"Estado: {machine.status}")
    if machine.description:
        parts.append(machine.description)
    return "\n".join(parts)


def work_order_index_text(work_order: WorkOrder, machine_name: str | None) -> str:
    parts = [f"ORDEN DE TRABAJO #{work_order.id}: {work_order.title}"]
    parts.append(f"Máquina: {machine_name or work_order.machine_id}")
    parts.append(f"Prioridad: {work_order.priority} | Estado: {work_order.status}")
    if work_order.description:
        parts.append(work_order.description)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Extracción y split de documentos
# ---------------------------------------------------------------------------

def extract_text(filename: str, data: bytes) -> str:
    """Extrae texto plano según la extensión del archivo.

    Formatos soportados: txt, md, json, pdf, docx y doc (Word legacy).
    Cualquier otra extensión se intenta decodificar como UTF-8.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # PdfError, PdfStreamError, PDFs cifrados…
            raise ValueError(f"No se pudo extraer texto del PDF: {exc}") from exc

    if ext == "docx":
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)

    if ext == "doc":
        return _extract_doc(data)

    if ext == "json":
        try:
            payload = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"El archivo JSON no es válido: {exc}") from exc
        return "\n".join(_flatten_json(payload))

    # txt, md, csv y cualquier otro: se intenta decodificar como UTF-8
    return data.decode("utf-8", errors="replace")


def _flatten_json(obj, prefix: str = "") -> list[str]:
    """Convierte un JSON en líneas 'clave: valor' para que el embedding capture
    mejor el significado (en vez de embeker llaves y comas del JSON crudo)."""
    lines: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            lines.extend(_flatten_json(value, f"{prefix}{key}."))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            lines.extend(_flatten_json(value, f"{prefix}{i}."))
    else:
        lines.append(f"{prefix.rstrip('.')}: {obj}")
    return lines


def _extract_doc(data: bytes) -> str:
    """Extrae texto de un .doc (Word 97-2003) usando antiword."""
    if shutil.which("antiword") is None:
        raise ValueError(
            "No se pudo extraer el .doc: falta la herramienta 'antiword' en el contenedor."
        )

    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ["antiword", tmp_path], capture_output=True, text=True, timeout=30
        )
    finally:
        os.unlink(tmp_path)

    if result.returncode != 0:
        raise ValueError(
            f"antiword no pudo extraer el documento: {result.stderr.strip() or 'error desconocido'}"
        )
    return result.stdout


def split_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    return splitter.split_text(text)


# ---------------------------------------------------------------------------
# Primitivas de indexación
# ---------------------------------------------------------------------------

def _embed_texts(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    batch = 100
    for i in range(0, len(texts), batch):
        vectors.extend(embeddings.embed_documents(texts[i : i + batch]))
    return vectors


def _chunk_metadata(
    *,
    chunk_id: int,
    source_type: str,
    name: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    machine_id: int | None = None,
    work_order_id: int | None = None,
    document_id: uuid.UUID | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "source": source_type,
        "name": name,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "machine_id": machine_id,
        "work_order_id": work_order_id,
        "document_id": str(document_id) if document_id else None,
    }


def _index_chunks(
    session: Session,
    *,
    source_type: str,
    space: str,
    texts: list[str],
    vectors: list[list[float]],
    name: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    machine_id: int | None = None,
    work_order_id: int | None = None,
    document_id: uuid.UUID | None = None,
) -> list[RagChunk]:
    chunks: list[RagChunk] = []
    metadatas: list[dict] = []
    for content, vector in zip(texts, vectors):
        chunk = RagChunk(
            source_type=source_type,
            entity_type=entity_type,
            entity_id=entity_id,
            machine_id=machine_id,
            work_order_id=work_order_id,
            document_id=document_id,
            content=content,
            embedding=vector,
            metadata_={"name": name},
        )
        session.add(chunk)
        session.flush()  # obtener el id serial antes de referenciarlo en FAISS
        chunks.append(chunk)
        metadatas.append(
            _chunk_metadata(
                chunk_id=chunk.id,
                source_type=source_type,
                name=name,
                entity_type=entity_type,
                entity_id=entity_id,
                machine_id=machine_id,
                work_order_id=work_order_id,
                document_id=document_id,
            )
        )

    faiss_store.add(space, texts, vectors, metadatas)
    return chunks


def _entity_chunks(
    session: Session, *, source_type: str, entity_id: int
) -> list[RagChunk]:
    return (
        session.query(RagChunk)
        .filter(RagChunk.source_type == source_type, RagChunk.entity_id == entity_id)
        .order_by(RagChunk.id)
        .all()
    )


def delete_entity_chunks(
    session: Session, *, source_type: str, entity_id: int, space: str
) -> int:
    """Borra de FAISS y de la BD los chunks de una entidad. Devuelve cuántos borró."""
    chunks = _entity_chunks(session, source_type=source_type, entity_id=entity_id)
    if not chunks:
        return 0
    faiss_store.delete_by_chunk_ids(space, {c.id for c in chunks})
    for chunk in chunks:
        session.delete(chunk)
    session.flush()
    return len(chunks)


# ---------------------------------------------------------------------------
# Indexación inicial
# ---------------------------------------------------------------------------

def index_machine(session: Session, machine: Machine) -> list[RagChunk]:
    """Indexa una máquina en el espacio 'machines'."""
    text = machine_index_text(machine)
    vector = embeddings.embed_query(text)
    return _index_chunks(
        session,
        source_type="machine",
        space="machines",
        texts=[text],
        vectors=[vector],
        name=machine.name,
        entity_type="machine",
        entity_id=machine.id,
        machine_id=machine.id,
    )


def index_work_order(
    session: Session, work_order: WorkOrder, machine_name: str | None
) -> list[RagChunk]:
    """Indexa una orden de trabajo en el espacio 'work_orders'."""
    text = work_order_index_text(work_order, machine_name)
    vector = embeddings.embed_query(text)
    return _index_chunks(
        session,
        source_type="work_order",
        space="work_orders",
        texts=[text],
        vectors=[vector],
        name=f"OT #{work_order.id} - {work_order.title}",
        entity_type="work_order",
        entity_id=work_order.id,
        machine_id=work_order.machine_id,
        work_order_id=work_order.id,
    )


def index_document(
    session: Session,
    document: Document,
    chunks_text: list[str],
    machine_id: int | None = None,
    work_order_id: int | None = None,
) -> list[RagChunk]:
    """Indexa los chunks de un documento en el espacio 'documents'."""
    vectors = _embed_texts(chunks_text)
    return _index_chunks(
        session,
        source_type="document",
        space="documents",
        texts=chunks_text,
        vectors=vectors,
        name=document.document_name,
        entity_type=document.entity_type,
        entity_id=document.entity_id,
        machine_id=machine_id,
        work_order_id=work_order_id,
        document_id=document.id,
    )


# ---------------------------------------------------------------------------
# Re-indexado automático al actualizar una entidad
# ---------------------------------------------------------------------------

def reindex_machine(session: Session, machine: Machine) -> tuple[list[RagChunk], bool]:
    """Si el texto indexado de la máquina cambió, borra los chunks viejos y
    re-indexa. Devuelve (chunks, reindexado)."""
    old = _entity_chunks(session, source_type="machine", entity_id=machine.id)
    new_text = machine_index_text(machine)

    if len(old) == 1 and old[0].content == new_text:
        return old, False  # nada relevante cambió: ni siquiera se llama a OpenAI

    # El embedding se genera ANTES de borrar nada: si OpenAI falla, la
    # transacción se revierte y el índice queda intacto.
    vector = embeddings.embed_query(new_text)
    delete_entity_chunks(session, source_type="machine", entity_id=machine.id, space="machines")

    chunks = _index_chunks(
        session,
        source_type="machine",
        space="machines",
        texts=[new_text],
        vectors=[vector],
        name=machine.name,
        entity_type="machine",
        entity_id=machine.id,
        machine_id=machine.id,
    )
    return chunks, True


def reindex_work_order(
    session: Session, work_order: WorkOrder, machine_name: str | None
) -> tuple[list[RagChunk], bool]:
    """Si el texto indexado de la OT cambió, borra los chunks viejos y re-indexa."""
    old = _entity_chunks(session, source_type="work_order", entity_id=work_order.id)
    new_text = work_order_index_text(work_order, machine_name)

    if len(old) == 1 and old[0].content == new_text:
        return old, False

    vector = embeddings.embed_query(new_text)
    delete_entity_chunks(
        session, source_type="work_order", entity_id=work_order.id, space="work_orders"
    )

    chunks = _index_chunks(
        session,
        source_type="work_order",
        space="work_orders",
        texts=[new_text],
        vectors=[vector],
        name=f"OT #{work_order.id} - {work_order.title}",
        entity_type="work_order",
        entity_id=work_order.id,
        machine_id=work_order.machine_id,
        work_order_id=work_order.id,
    )
    return chunks, True
