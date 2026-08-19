# `app/routers/v1/` — API versionada

La API se maneja **por versiones**. Cada versión es una carpeta con sus propios
routers; la activa ahora es **v1** y todos sus endpoints quedan bajo el prefijo
**`/api/v1`**:

| Router        | Ruta(s) bajo `/api/v1` |
|---|---|
| `machines`    | `POST /machines`, `GET /machines`, `PATCH /machines/{id}` |
| `work_orders` | `POST /work-orders`, `GET /work-orders`, `PATCH /work-orders/{id}` |
| `ingest`      | `POST /ingest`, `GET /documents`, `GET /documents/{id}/file` |
| `chat`        | `POST /chat/sessions`, `POST /chat/sessions/{id}/messages`, `GET /chat/sessions/{id}/messages` |
| `admin`       | `POST /reindex` |

## Cómo funciona el prefijo

Los routers definen sus rutas **sin versión** (`router = APIRouter(prefix="/machines")`).
El prefijo `/api/v1` se aplica una sola vez en `routers/v1/__init__.py`, donde
se construye `api_router`:

```python
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(machines.router)
...
```

`app/main.py` solo registra ese `api_router`. Así, cada versión es
autocontenida y la app principal no se llena de imports por ruta.

## Añadir una v2 en el futuro

1. Crea `app/routers/v2/` copiando la estructura de `v1/`.
2. Ajusta los routers a los nuevos contratos (`schemas/`) y servicios.
3. En `app/routers/v2/__init__.py`, monta su propio `api_router` con
   `prefix="/api/v2"`.
4. Regístralo en `app/main.py`:

```python
from .routers.v1 import api_router as v1
from .routers.v2 import api_router as v2

app.include_router(v1)
app.include_router(v2)  # convivencia de versiones mientras migras clientes
```

> `GET /health` se mantiene fuera de versiones: es un check de
> infraestructura, no un endpoint de negocio.
