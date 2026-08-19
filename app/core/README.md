# `app/core/` — Infraestructura base

Capa de **infraestructura**: configuración, acceso a datos y logging.
Nada dentro de `core/` importa de `library/`, `services/` o `routers/` — es la
base de la pirámide, y el resto de la app depende de ella.

| Archivo      | Funcionalidad |
|---|---|
| `config.py`  | `Settings` (pydantic-settings): lee variables de entorno (`.env`) y expone la configuración global como `settings`. |
| `db.py`      | `engine` (SQLAlchemy), `SessionLocal` (fábrica de sesiones), `Base` (declarative base) e `init_db()` (crea las tablas). |
| `models.py`  | Modelos ORM: `Machine`, `WorkOrder`, `Document`, `RagChunk`, `ChatSession`, `ChatMessage`, `CitationLog`, `LogEntry`. Son la **fuente de verdad** de los datos. |
| `log.py`     | `log_event()`: escribe eventos info/error en `logs_table` sin romper nunca el flujo principal. |

## Regla de oro

- `core/` no importa a ninguna otra carpeta de `app/`.
- `library/`, `services/` y `routers/` importan desde `core/`:

```python
from ..core.config import settings
from ..core.db import SessionLocal
from ..core.models import Machine
```

## ¿Por qué `models.py` está aquí y no en `schemas/`?

`models.py` es el **esquema de la base de datos** (SQLAlchemy ORM); `schemas/`
son los **contratos de la API** (Pydantic). Se mantienen separados a propósito:
la BD y la API pueden evolucionar de forma independiente.
