from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import faiss_store
from .db import init_db
from .routers import admin, chat, ingest, machines, work_orders


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

app.include_router(machines.router)
app.include_router(work_orders.router)
app.include_router(ingest.router)
app.include_router(chat.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok", "faiss_spaces": faiss_store.spaces()}
