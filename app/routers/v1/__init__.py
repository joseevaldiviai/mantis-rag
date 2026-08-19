"""API v1.

Cada router de esta carpeta define sus rutas sin versión (p. ej. `/machines`);
el prefijo `/api/v1` se aplica aquí, de modo que el endpoint final queda en
`/api/v1/machines`. Para añadir una v2 en el futuro, crea `routers/v2/` con la
misma estructura y registra su `api_router` en `app/main.py`.
"""

from fastapi import APIRouter

from . import admin, chat, ingest, machines, work_orders

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(machines.router)
api_router.include_router(work_orders.router)
api_router.include_router(ingest.router)
api_router.include_router(chat.router)
api_router.include_router(admin.router)
