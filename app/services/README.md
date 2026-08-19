# `app/services/` — Lógica de negocio (casos de uso)

Capa de **aplicación**: orquesta los componentes de `library/` y `core/` para
cumplir un caso de uso del negocio. Los routers quedan **delgados** (solo HTTP:
validar con `schemas/`, llamar al servicio, traducir errores a HTTP).

| Archivo       | Funcionalidad |
|---|---|
| `qa_service.py` | Flujo completo de pregunta-respuesta RAG: embebe la pregunta → busca en todos los espacios FAISS con filtros → fusiona y ordena por score → construye el contexto → genera la respuesta con el LLM → guarda mensajes y `citation_logs`. |

`answer_question(session, chat_session, question, top_k, filters)` es el caso de
uso principal: recibe una sesión ya abierta y devuelve `{message_id, answer,
sources}`.

## Cómo crecer esta carpeta

Si mañana aparece "enviar una OT por email" o "generar un informe de
mantenimiento", lo natural es añadir aquí un servicio por caso de uso:

```text
services/
├── qa_service.py       # responder preguntas sobre el CMMS
├── notification_service.py   # (ejemplo) avisos de OTs vencidas
└── report_service.py         # (ejemplo) informes de mantenimiento
```

Regla: un servicio no sabe que existe HTTP; recibe datos y devuelve resultados.
