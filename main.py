"""Punto de entrada del proyecto Mantis RAG.

La aplicación FastAPI vive en `app/main.py`. Para ejecutarla:

    uvicorn app.main:app --host 0.0.0.0 --port 8000

o, con Docker:

    docker compose up --build

Estructura interna de `app/`:

    core/      infraestructura (config, db, models, log)
    schemas/   contratos Pydantic de la API, organizados por dominio
    library/   componentes técnicos reutilizables (embeddings, FAISS, indexing, storage)
    services/  lógica de negocio (qa_service)
    routers/   endpoints por versión (v1 -> /api/v1/...)
"""
