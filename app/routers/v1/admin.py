from fastapi import APIRouter, HTTPException

from ...core.log import log_event
from ...library import faiss_store
from ...schemas import ReindexRequest, ReindexResponse

router = APIRouter(tags=["admin"])


@router.post("/reindex", response_model=ReindexResponse)
def reindex(payload: ReindexRequest | None = None):
    """Reconstruye el/los índice(s) FAISS desde rag_chunks.

    Útil como red de seguridad: si el índice se corrompe o se desincroniza con
    la BD, este endpoint lo reconstruye entero (o solo un espacio).
    """
    space = payload.space if payload else None
    try:
        counts = faiss_store.rebuild(space)
    except Exception as exc:
        log_event("error", "Fallo al reconstruir el índice FAISS", exc=exc)
        raise HTTPException(
            status_code=500, detail=f"Error reconstruyendo el índice: {exc}"
        ) from exc

    log_event("info", f"Índice FAISS reconstruido: {counts}")
    return ReindexResponse(spaces=counts)
