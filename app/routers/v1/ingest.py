import uuid

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from ...core.db import SessionLocal
from ...core.log import log_event
from ...core.models import Document, Machine, WorkOrder
from ...library import storage
from ...library.indexing import extract_text, index_document, split_text
from ...schemas import DocumentResponse, IngestResponse

router = APIRouter(tags=["ingest"])

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "txt": "text/plain",
    "md": "text/markdown",
    "json": "application/json",
    "csv": "text/csv",
}


def _content_type_for(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return CONTENT_TYPES.get(ext, "application/octet-stream")


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    file: UploadFile = File(...),
    machine_id: int | None = Form(default=None),
    work_order_id: int | None = Form(default=None),
    ref_link: str = Form(default=""),
    uploaded_by: str | None = Form(default=None),
):
    """Sube un documento (txt, md, json, pdf, docx, doc) y lo indexa en FAISS
    (espacio documents).

    Si el storage (Firebase Storage / GCS) está configurado, el archivo
    original se guarda en `documents/{document_id}/{nombre}` y `storage_path`
    queda en la respuesta; si no, solo se indexan los chunks.

    Opcionalmente se adjunta a una máquina o a una orden de trabajo mediante
    machine_id / work_order_id, para poder filtrar la búsqueda por entidad.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Falta el nombre del archivo.")
    if machine_id and work_order_id:
        raise HTTPException(
            status_code=400,
            detail="Adjunta el documento a una máquina O a una orden de trabajo, no a ambas.",
        )

    data = file.file.read()
    try:
        text = extract_text(file.filename, data).strip()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not text:
        raise HTTPException(status_code=400, detail="No se pudo extraer texto del archivo.")

    chunks_text = split_text(text)

    with SessionLocal() as session:
        # Resolver la entidad a la que se adjunta
        entity_type: str | None = None
        entity_id: int | None = None
        machine_id_fk: int | None = None
        work_order_id_fk: int | None = None

        if machine_id:
            machine = session.get(Machine, machine_id)
            if machine is None:
                raise HTTPException(status_code=404, detail=f"No existe la máquina {machine_id}.")
            entity_type, entity_id = "machine", machine.id
            machine_id_fk = machine.id
        elif work_order_id:
            wo = session.get(WorkOrder, work_order_id)
            if wo is None:
                raise HTTPException(
                    status_code=404, detail=f"No existe la orden de trabajo {work_order_id}."
                )
            entity_type, entity_id = "work_order", wo.id
            work_order_id_fk = wo.id

        document = Document(
            id=uuid.uuid4(),
            entity_type=entity_type,
            entity_id=entity_id,
            document_name=file.filename,
            ref_link=ref_link,
            uploaded_by=uploaded_by,
        )
        session.add(document)

        # Guardar el original en GCS (si está configurado). El id se genera en
        # Python, así que la ruta del blob es estable antes del flush.
        storage_path: str | None = None
        if storage.storage_enabled():
            try:
                storage_path = storage.upload_original(
                    document.id,
                    file.filename,
                    data,
                    _content_type_for(file.filename),
                )
                document.storage_path = storage_path
            except Exception as exc:
                session.rollback()
                log_event(
                    "error", "Fallo al subir el original a Storage",
                    entity_type=entity_type, entity_id=entity_id, exc=exc,
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Error subiendo el archivo a Firebase Storage: {exc}",
                ) from exc
        else:
            log_event(
                "info", f"Storage no configurado: {file.filename} se indexa sin guardar el original",
                entity_type=entity_type, entity_id=entity_id,
            )

        session.flush()

        try:
            chunks = index_document(
                session,
                document,
                chunks_text,
                machine_id=machine_id_fk,
                work_order_id=work_order_id_fk,
            )
        except Exception as exc:
            session.rollback()
            # Limpiar el blob huérfano si ya se subió
            if storage_path:
                try:
                    storage._get_bucket().blob(storage_path).delete()
                except Exception:
                    pass
            log_event(
                "error", "Fallo al indexar documento",
                entity_type=entity_type, entity_id=entity_id, exc=exc,
            )
            raise HTTPException(
                status_code=500, detail=f"Error indexando el documento: {exc}"
            ) from exc

        session.commit()
        log_event(
            "info", f"Documento {file.filename} indexado ({len(chunks)} chunks)"
                    + (f", original en {storage_path}" if storage_path else ""),
            entity_type=entity_type, entity_id=entity_id,
        )

    return IngestResponse(
        document_id=document.id,
        document_name=file.filename,
        entity_type=entity_type,
        entity_id=entity_id,
        num_chunks=len(chunks),
        storage_path=storage_path,
    )


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(entity_type: str | None = None, entity_id: int | None = None):
    """Lista los documentos subidos. Filtro opcional por entidad."""
    with SessionLocal() as session:
        query = session.query(Document).order_by(Document.created_at.desc())
        if entity_type:
            query = query.filter(Document.entity_type == entity_type)
        if entity_id is not None:
            query = query.filter(Document.entity_id == entity_id)
        return [
            DocumentResponse(
                id=d.id,
                document_name=d.document_name,
                ref_link=d.ref_link,
                entity_type=d.entity_type,
                entity_id=d.entity_id,
                uploaded_by=d.uploaded_by,
                storage_path=d.storage_path,
                created_at=d.created_at,
            )
            for d in query.all()
        ]


@router.get("/documents/{document_id}/file")
def download_document_file(document_id: uuid.UUID):
    """Descarga el archivo original desde Firebase Storage / GCS."""
    with SessionLocal() as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail=f"No existe el documento {document_id}.")
        if not document.storage_path:
            raise HTTPException(
                status_code=404,
                detail="Este documento no tiene archivo original (storage no configurado "
                       "cuando se subió, o solo se indexaron los chunks).",
            )

        try:
            data = storage.download_original(document.storage_path)
        except Exception as exc:
            log_event("error", "Fallo al descargar el original", entity_type="document",
                      entity_id=document_id, exc=exc)
            raise HTTPException(
                status_code=500, detail=f"Error descargando el archivo: {exc}"
            ) from exc
        if data is None:
            raise HTTPException(
                status_code=503,
                detail="El almacenamiento no está disponible en este momento.",
            )

    filename = document.document_name.replace('"', "_")
    return Response(
        content=data,
        media_type=_content_type_for(document.document_name),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
