# Auditoría general del código

Fecha: 2026-08-15 · Alcance: todo `app/`, `dump_db.py`, `main.py`, `README.md`

Leyenda: 🔴 alta · 🟠 media · 🟡 baja · ✅ positivo

---

## 🔴 Hallazgos de severidad alta

### A1. No hay autenticación en ningún endpoint
- **Dónde:** `routers/v1/*` (todos), especialmente `POST /api/v1/reindex`.
- **Qué pasa:** cualquier persona con acceso a la API puede crear/borrar
  datos, subir documentos y **reconstruir los índices** (cuesta OpenAI por cada
  chunk). Hoy el puerto solo se expone en local, pero en un despliegue real
  esto es un riesgo.
- **Sugerencia:** API key simple (header `X-API-Key`) como primer paso, o
  OAuth/JWT si hay usuarios. Al menos proteger `admin` (reindex).

### A2. Sin `OPENAI_API_KEY` la app no arranca
- **Dónde:** `library/embeddings.py` (los clientes OpenAI se crean en el
  import del módulo).
- **Qué pasa:** `OpenAIEmbeddings()` se instancia al importar, con
  `settings.openai_api_key` (vacío por defecto). Sin clave, el arranque
  falla aunque solo quieras usar endpoints que no tocan el LLM.
- **Sugerencia:** validar la clave en `lifespan` con un mensaje claro, o
  crear los clientes de forma perezosa (lazy) la primera vez que se usen.
  (En Docker ya se exige con `${OPENAI_API_KEY:?}`.)

### A3. Las mutaciones de FAISS no son transaccionales
- **Dónde:** `library/indexing.py` (`reindex_*`, `delete_entity_chunks`) y
  `library/faiss_store.py`.
- **Qué pasa:** si en un reindex la operación de FAISS falla *después* de
  borrar (p. ej. entre `delete_by_chunk_ids` y `add`), la BD se revierte con
  rollback pero el índice FAISS queda a medias (ya guardado en disco). La BD
  y el índice pueden desincronizarse.
- **Sugerencia:** aceptar el riesgo (existe `POST /api/v1/reindex` como red de
  seguridad) o, como mejora, envolver las operaciones FAISS en un "undo" o
  marcar el índice como sucio para reconstruirlo en el próximo arranque.

---

## 🟠 Severidad media

### M1. CRUD incompleto: no hay DELETE ni GET por id
- **Dónde:** `routers/v1/machines.py`, `work_orders.py`, `ingest.py`.
- **Qué pasa:** solo existe crear, listar y actualizar. No se puede eliminar
  una máquina/OT/documento por API, ni consultar uno solo. Además, el borrado
  de una entidad **no limpia sus chunks** de FAISS/BD (los índices quedarían
  con datos huérfanos).
- **Sugerencia:** añadir `GET /{id}` y `DELETE /{id}`. El DELETE debe borrar
  los chunks (`delete_entity_chunks`) y, si hay storage, el blob original.

### M2. `list_work_orders` hace N+1 consultas
- **Dónde:** `routers/v1/work_orders.py` → `_to_response()` accede a
  `wo.machine.name`.
- **Qué pasa:** por cada OT se dispara una query extra para cargar la máquina
  (lazy loading). Con cientos de OTs, decenas de queries.
- **Sugerencia:** `selectinload(WorkOrder.machine)` o un `join` en la query.

### M3. Sin paginación en los listados
- **Dónde:** `GET /api/v1/machines`, `GET /api/v1/work-orders`,
  `GET /api/v1/documents`, historial de chat.
- **Qué pasa:** devuelven todo. Con datos reales crecerá.
- **Sugerencia:** parámetros `limit`/`offset` (o cursor) como primer paso.

### M4. `signed_url()` está sin usar (código muerto)
- **Dónde:** `library/storage.py` (`signed_url`) y `routers/v1/ingest.py`.
- **Qué pasa:** la función existe pero ningún endpoint la llama; el
  `storage_path` se expone tal cual en `DocumentResponse`.
- **Sugerencia:** añadir `GET /api/v1/documents/{id}/signed-url` que devuelva
  una URL firmada temporal (más seguro que exponer el blob) o eliminar la
  función.

### M5. El historial de chat no alimenta al LLM
- **Dónde:** `services/qa_service.py`.
- **Qué pasa:** se guardan los mensajes pero la respuesta solo usa los chunks
  recuperados; no hay memoria conversacional. Es un diseño válido (QA sobre
  documentos), pero hay que tenerlo presente si se espera un chat con
  contexto de la conversación.
- **Sugerencia:** documentarlo (ya está en el manual) y, si se quiere, pasar
  los últimos N mensajes al prompt.

---

## 🟡 Severidad baja / estilo

### B1. Acceso a miembro privado desde el router
- **Dónde:** `routers/v1/ingest.py` → `storage._get_bucket().blob(...).delete()`.
- **Sugerencia:** exponer `storage.delete_original(storage_path)` como función
  pública.

### B2. El servicio hace `commit` y el router hace `rollback`
- **Dónde:** `services/qa_service.py` (`session.commit()`) vs.
  `routers/v1/chat.py` (`session.rollback()` en el except).
- **Qué pasa:** la responsabilidad de la transacción queda partida entre dos
  capas. Funciona, pero es frágil si se reutiliza el servicio.
- **Sugerencia:** mover el `commit` al router (o al caller) y dejar que el
  servicio solo trabaje sobre la sesión.

### B3. Duplicación del campo "name"
- **Dónde:** `rag_chunks.metadata_["name"]` (BD) y el metadata de FAISS
  generado en `faiss_store._metadata_for_chunk()`.
- **Sugerencia:** mantener la BD como única fuente y derivar el metadata de
  FAISS de ella (ya se hace al reconstruir, pero en `_index_chunks` se
  escribe a mano en dos sitios).

### B4. `get` de `faiss_store` no se usa
- **Dónde:** `library/faiss_store.py` → `get()`.
- **Qué pasa:** función pública sin consumidores.
- **Sugerencia:** usarla en algún helper o eliminarla.

### B5. Sin tests
- **Qué pasa:** cero pruebas en el repo; el refactor se validó con
  compilación y revisión de imports, pero no hay red de seguridad.
- **Sugerencia:** empezar por tests de integración de los endpoints
  (FastAPI TestClient + BD SQLite/Postgres de prueba) y unit tests de
  `indexing` y `qa_service`.

### B6. Docstrings mixtos EN/ES
- **Qué pasa:** hay docstrings en inglés (modelos, faiss_store) y en español
  (routers, indexing). No es un error, pero conviene unificar (el proyecto
  habla en español).

---

## ✅ Lo que está bien hecho

- **Re-indexado seguro:** el embedding nuevo se genera *antes* de borrar el
  viejo (A3 es el caso límite, pero el diseño evita el fallo común de borrar
  y luego fallar al embeder).
- **Ranking fusionado por similitud coseno** con vectores normalizados:
  comparable entre espacios.
- **`rag_chunks` como fuente de verdad:** si FAISS se pierde, se reconstruye
  desde la BD (`/reindex`).
- **Degradación elegante del storage:** sin GCS configurado, la ingesta
  sigue funcionando (solo chunks).
- **Filtros por entidad y ámbito de sesión** bien resueltos (los filtros
  explícitos ganan al ámbito).
- **`log_event` nunca rompe el flujo** (try/except silencioso por diseño).
- **Estructura por capas clara** tras el refactor (core → library → services
  → routers) con READMEs en cada carpeta.

---

## Prioridades sugeridas

1. **Seguridad mínima** (A1): API key en `admin` al menos.
2. **DELETE + GET por id** (M1) con limpieza de chunks.
3. **Paginación** (M3) y **fix N+1** (M2).
4. **Tests** (B5) — idealmente antes de seguir añadiendo features.
5. **Signed URL para descargas** (M4).
