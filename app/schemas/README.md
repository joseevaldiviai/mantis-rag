# `app/schemas/` — Contratos de la API (Pydantic)

Define **qué recibe y qué devuelve cada endpoint** usando Pydantic. FastAPI
usa estos modelos para validar las peticiones, documentar la API en `/docs` y
serializar las respuestas.

Están organizados **por dominio**, uno por módulo, para que cada router importe
solo lo suyo:

| Módulo        | Contenido | Lo usan los routers |
|---|---|---|
| `machine.py`  | `MachineBase`, `MachineCreate`, `MachineUpdate`, `MachineResponse`, `MachineUpdateResponse` | `machines` |
| `work_order.py` | `WorkOrderCreate`, `WorkOrderUpdate`, `WorkOrderResponse`, `WorkOrderUpdateResponse` | `work_orders` |
| `ingest.py`   | `IngestResponse`, `DocumentResponse` | `ingest` |
| `chat.py`     | `ChatSessionCreate/Response`, `ChatFilters`, `ChatMessageRequest/Response`, `Source`, `ChatMessageRecord` | `chat` |
| `admin.py`    | `ReindexRequest`, `ReindexResponse` | `admin` |

`__init__.py` re-exporta todo, así que los routers importan de un solo sitio:

```python
from ...schemas import MachineCreate, MachineResponse
```

## Convenciones

- `*Create` / `*Update`: lo que el cliente envía (body de POST/PATCH).
- `*Response`: lo que el servidor devuelve (con `id`, `created_at`, etc.).
- `*Base`: campos comunes que comparten Create y Response.
- `Field(..., pattern=...)`, `min_length`, `ge/le`: validación declarativa;
  si el cliente manda algo inválido, FastAPI responde `422` automáticamente.
