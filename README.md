# Mantis CMMS RAG

Sistema de Retrieval-Augmented Generation orientado a **CMMS** (gestión de
mantenimiento): registra **maquinarias** y **órdenes de trabajo**, las indexa con
embeddings y responde preguntas usando **FAISS** para la búsqueda vectorial.

Stack:

- **LangChain** (embeddings, splitter, cadena de QA) + **OpenAI**
- **FastAPI** (API REST)
- **PostgreSQL** (datos estructurados: máquinas, OTs, chunks, chat, citas, logs)
- **FAISS** (búsqueda vectorial con índices por espacio y ranking por similitud)
- **Docker Compose**

## Búsqueda vectorial: espacios, índice y ranking

- **Espacios (namespaces):** hay un índice FAISS separado por tipo de entidad:
  `machines`, `work_orders` y `documents`. Al preguntar se busca en los tres y se
  fusionan los resultados.
- **Índice:** `IndexFlatIP` con `normalize_L2` (vectores normalizados) → el score
  es la **similitud coseno** (mayor = más relevante). Los índices se persisten en
  disco (`FAISS_INDEX_DIR`) y se reconstruyen desde la BD si se pierden.
- **Ranking:** los resultados de todos los espacios se ordenan por score en un
  ranking global. Cada respuesta guarda en `citation_logs` qué chunks citó y con
  qué `relevance_score`, para auditar y afinar la búsqueda.
- **Afinado:** `TOP_K` (chunks que entran en el contexto) y
  `MIN_RELEVANCE_SCORE` (umbral mínimo de similitud; p.ej. `0.55`).
  Los filtros por entidad (máquina, OT) acotan la búsqueda al metadata.

Los embeddings son **contextuales al dominio**: al indexar una máquina se
embebe "MAQUINARIA: nombre (código) · ubicación · estado · descripción", y en
las OTs se incluye máquina, prioridad y estado.

## Puesta en marcha

```bash
cp .env.example .env          # y rellena OPENAI_API_KEY
docker compose up --build
```

API en `http://localhost:8000`, documentación en `http://localhost:8000/docs`.

## Flujo de uso

```bash
# 1. Registrar maquinaria (se indexa automáticamente en FAISS)
curl -X POST http://localhost:8000/machines \
  -H "Content-Type: application/json" \
  -d '{"code":"P-101","name":"Bomba centrífuga","description":"Bomba de proceso de 30 HP…","location":"Planta A"}'

# 2. Registrar una orden de trabajo (también se indexa)
curl -X POST http://localhost:8000/work-orders \
  -H "Content-Type: application/json" \
  -d '{"machine_id":1,"title":"Cambio de rodamientos","description":"Ruido en el eje…","priority":"high"}'

# 3. Subir un documento, opcionalmente adjunto a una máquina u OT
curl -F "file=@manual_bomba.pdf" -F "machine_id=1" http://localhost:8000/ingest

# 4. Crear una sesión de chat (opcional: acotada a una entidad)
curl -X POST http://localhost:8000/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{"entity_type":"machine","entity_id":1,"title":"Diagnóstico bomba P-101"}'

# 5. Preguntar dentro de la sesión (devuelve respuesta + fuentes con score)
curl -X POST http://localhost:8000/chat/sessions/<session_id>/messages \
  -H "Content-Type: application/json" \
  -d '{"question":"¿Qué mantenimiento requiere la bomba P-101?","top_k":5}'

# 6. Ver historial / estado
curl http://localhost:8000/chat/sessions/<session_id>/messages
```

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/machines` | Registra maquinaria y la indexa (espacio `machines`) |
| `GET` | `/machines` | Lista maquinarias |
| `PATCH` | `/machines/{id}` | Actualiza la máquina y re-indexa en FAISS si cambió el texto indexado |
| `POST` | `/work-orders` | Registra OT y la indexa (espacio `work_orders`) |
| `GET` | `/work-orders` | Lista órdenes de trabajo |
| `PATCH` | `/work-orders/{id}` | Actualiza la OT y re-indexa en FAISS si cambió el texto indexado |
| `POST` | `/ingest` | Sube documento (txt/md/json/pdf/docx/doc), opcionalmente ligado a máquina/OT. Guarda el original si hay storage configurado |
| `GET` | `/documents` | Lista documentos (filtro opcional por entidad) |
| `GET` | `/documents/{id}/file` | Descarga el archivo original desde Firebase Storage / GCS |
| `POST` | `/chat/sessions` | Crea sesión, opcionalmente acotada a una entidad |
| `POST` | `/chat/sessions/{id}/messages` | Pregunta → busca en FAISS, genera respuesta, guarda citas |
| `GET` | `/chat/sessions/{id}/messages` | Historial de la sesión |
| `POST` | `/reindex` | Reconstruye el/los índice(s) FAISS desde `rag_chunks` (red de seguridad) |
| `GET` | `/health` | Estado + espacios FAISS activos |

## Re-indexado automático

Al hacer `PATCH` sobre una máquina u OT, la API compara el texto indexado
actual con el nuevo (código, nombre, descripción, ubicación, estado…). Si
cambió:

1. Genera el embedding del nuevo texto **antes de borrar nada**: si OpenAI
   falla, la transacción se revierte y el índice queda intacto.
2. Borra los chunks viejos de FAISS y de `rag_chunks`.
3. Indexa el texto nuevo en su espacio y persiste el índice.

Si nada relevante cambió, no llama a OpenAI y devuelve `reindexed: false`.
La respuesta del `PATCH` incluye `reindexed` y `num_chunks` para verlo.

```bash
# Cambiar el estado de una máquina -> se re-indexa sola
curl -X PATCH http://localhost:8000/machines/1 \
  -H "Content-Type: application/json" \
  -d '{"status":"maintenance"}'
```

## Esquema (PostgreSQL)

```
machines        maquinarias (código, nombre, descripción, ubicación, estado)
work_orders     órdenes de trabajo (máquina, título, prioridad, estado…)
documents       documentos subidos, opcionalmente ligados a una entidad
rag_chunks      chunks indexados (texto, embedding, metadata, source_type)
chat_sessions   sesiones de chat, acotables a máquina/OT
chat_messages   mensajes user/assistant
citation_logs   qué chunks citó cada respuesta + relevance_score (ranking)
logs_table      eventos info/error
```

## Configuración

| Variable | Descripción | Defecto |
|---|---|---|
| `OPENAI_API_KEY` | Clave OpenAI | *(obligatoria)* |
| `DATABASE_URL` | Conexión a Postgres | `postgresql+psycopg2://rag:rag@localhost:5432/rag` |
| `EMBEDDING_MODEL` | Modelo de embeddings | `text-embedding-3-small` |
| `LLM_MODEL` | Modelo generativo | `gpt-4o-mini` |
| `TOP_K` | Chunks finales en el contexto | `5` |
| `MIN_RELEVANCE_SCORE` | Umbral de similitud (0 = off) | `0.0` |
| `FAISS_INDEX_DIR` | Ruta de los índices FAISS | `data/faiss` |

## Estructura

```
app/
├── main.py            # FastAPI + lifespan (tablas + carga/reconstrucción de FAISS)
├── config.py          # Settings
├── db.py              # Engine, sesión
├── models.py          # machines, work_orders, documents, rag_chunks, chat, citations, logs
├── schemas.py         # Pydantic
├── embeddings.py      # OpenAIEmbeddings, ChatOpenAI, cadena QA (prompt CMMS)
├── faiss_store.py     # Espacios FAISS, persistencia y búsqueda con ranking
├── indexing.py        # Indexación contextual de máquinas/OTs/documentos
├── qa_service.py      # Búsqueda multi-espacio + respuesta + citation_logs
├── log.py             # logs_table
└── routers/           # machines, work_orders, ingest, chat
```

## Almacenamiento del archivo original (Firebase Storage)

Por defecto la ingesta solo guarda los **chunks** (texto + embedding); el PDF/DOCX
original se descarta tras extraerle el texto. Si quieres conservar el original,
configura `GCS_BUCKET` con el bucket de Firebase Storage (al crear el proyecto
Firebase se crea `<proyecto>.appspot.com`, y Firebase Storage es una capa sobre
Google Cloud Storage):

```bash
GCS_BUCKET=mi-proyecto.appspot.com
# Credenciales de la service account, de una de estas dos formas:
GCS_CREDENTIALS=/ruta/clave.json
# o el contenido del JSON directamente (más cómodo en Docker):
GCS_CREDENTIALS_JSON='{"type": "service_account", ...}'
```

Con storage configurado, `/ingest` sube el archivo a `documents/{id}/{nombre}`
y devuelve `storage_path`; `GET /documents/{id}/file` lo descarga. Sin bucket,
la API funciona igual que antes (solo chunks) — el storage es opcional.

## Dump de la base de datos

`dump_db.py` genera un archivo reimportable con el esquema y los datos de
Postgres (o JSON por colecciones para Firestore):

```bash
python dump_db.py                      # -> dumps/dump_<fecha>.sql
python dump_db.py --format json        # -> dumps/dump_<fecha>.json (Firestore)
python dump_db.py --tables machines,work_orders --output backup.sql
python dump_db.py --schema-only        # solo CREATE TABLE
```

Dentro del contenedor:

```bash
docker compose exec api python dump_db.py
```

Restaurar el SQL en una BD vacía:

```bash
psql -U rag -d rag < dumps/dump_<fecha>.sql
```

> **Sobre Firebase:** Firestore es NoSQL y no acepta SQL. Si quieres subir los
> datos a Firestore, usa `--format json` (genera una colección por tabla:)
> `machines`, `work_orders`, `rag_chunks`, etc. El `.sql` sirve como copia de
> seguridad para restaurar en Postgres (o subirlo a Firebase Storage como
> archivo, si solo quieres guardar el backup).

## Notas

- Las máquinas y OTs se **re-indexan solas** al actualizarse (`PATCH`), porque
  su texto indexado incluye estado, prioridad, etc. (data viva).
- Si el índice se desincroniza, `POST /reindex` lo reconstruye desde `rag_chunks`
  (todos los espacios o solo uno con `{"space": "machines"}`).
- **Ingesta:** `txt`, `md`, `json` (se aplana a `clave: valor`), `pdf`, `docx`
  y `doc` (Word legacy, vía `antiword`).
- Los índices FAISS se persisten en el volumen `faiss_data` (Docker). Si se
  borran, se reconstruyen automáticamente desde `rag_chunks` al arrancar.
- `IndexFlatIP` es una búsqueda exacta, suficiente para un CMMS. Para miles de
  chunks puedes migrar a `IndexHNSWFlat` (aproximada, mucho más rápida).
- El umbral `MIN_RELEVANCE_SCORE` y los filtros por entidad son el primer paso
  para afinar; el siguiente nivel sería añadir un reranker (p.ej. Cohere) sobre
  el ranking coseno.
