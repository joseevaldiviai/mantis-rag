from contextlib import asynccontextmanager

from fastapi import FastAPI

from .core.db import init_db
from .library import faiss_store
from .routers.v1 import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    faiss_store.init_stores()  # carga o reconstruye los índices FAISS
    yield


app = FastAPI(
    title="Mantis CMMS RAG API",
    description=(
        "RAG para CMMS: maquinarias, órdenes de trabajo y documentos indexados "
        "con embeddings en FAISS (espacios por entidad) y ranking por similitud."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

# Toda la API vive bajo /api/v1 (ver app/routers/v1/__init__.py).
# El endpoint /health se mantiene fuera de versiones (check de infraestructura).
app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok", "faiss_spaces": faiss_store.spaces()}
