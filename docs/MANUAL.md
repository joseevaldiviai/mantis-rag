# Manual: RAG para CMMS (Mantis)

Este manual está pensado para **aprender cómo funciona un sistema RAG** usando
este proyecto como ejemplo real. Léelo en orden la primera vez; luego úsalo
como referencia.

---

## 1. ¿Qué es un RAG?

**RAG = Retrieval-Augmented Generation** (generación aumentada por recuperación).

Un LLM (GPT-4o-mini, etc.) solo sabe lo que aprendió al entrenarse. Si le
preguntas por *"la bomba P-101 de tu planta"*, no tiene ni idea de qué es: no
está en su entrenamiento. RAG resuelve eso en **dos pasos**:

1. **Recuperación (Retrieval):** busca en *tus* documentos (manuales, órdenes
   de trabajo, fichas de máquinas) los fragmentos más relevantes para la
   pregunta.
2. **Generación (Generation):** mete esos fragmentos como **contexto** en el
   prompt del LLM y le pide que responda *usando solo ese contexto*.

Resultado: el modelo responde sobre **tu dominio** sin haber sido reentrenado,
y con **fuentes** que puedes citar.

```
          TUS DOCUMENTOS                        PREGUNTA DEL USUARIO
               │                                        │
        ┌──────▼──────┐                          ┌──────▼──────┐
        │  Chunking   │                          │  Embedding  │
        │  (partir    │                          │  (vector    │
        │  el texto)  │                          │  de la      │
        └──────┬──────┘                          │  pregunta)  │
               ▼                                 └──────┬──────┘
        ┌──────────────┐                                │
        │  Embeddings  │  cada chunk → vector           │
        └──────┬───────┘                                │
               ▼                                        │
        ┌──────────────┐    búsqueda por similitud      │
        │ Índice       │◄───────────────────────────────┘
        │ vectorial    │   (coseno entre vectores)
        └──────┬───────┘
               ▼
        ┌──────────────────────────────┐
        │ top_k chunks más relevantes  │
        │  → se convierten en CONTEXTO │
        └──────────────┬───────────────┘
                       ▼
        ┌──────────────────────────────┐
        │  PROMPT:  Contexto + Pregunta│──►  LLM  ──►  RESPUESTA + FUENTES
        └──────────────────────────────┘
```

### Vocabulario mínimo

| Término | Qué es |
|---|---|
| **Chunk** | Fragmento de texto (p. ej. 1000 caracteres con 200 de solape). Los LLM tienen límite de contexto, así que hay que partir los documentos. |
| **Embedding** | Vector de números que "resume" el significado de un texto. Textos parecidos quedan cerca en el espacio vectorial. |
| **Índice vectorial** | Estructura que guarda los vectores y permite buscar los más cercanos a otro vector (FAISS en este proyecto). |
| **Similitud coseno** | Cómo de "parecidos" son dos vectores (0 = nada, 1 = idénticos). Aquí el score de búsqueda. |
| **top_k** | Cuántos chunks se meten en el contexto (aquí `TOP_K`, por defecto 5). |
| **Contexto** | Los chunks recuperados, pegados en el prompt antes de la pregunta. |
| **Fuente / citación** | Metadatos del chunk (de qué máquina/OT/documento salió) para que el usuario pueda verificar. |

---

## 2. Cómo funciona este sistema

### 2.1 Arquitectura por capas

El proyecto se dividió en capas con dependencias **de arriba hacia abajo**:
los routers (HTTP) llaman a servicios (lógica) que usan la librería técnica
(motores) sobre la infraestructura (BD, config). Las flechas indican
"importa de / depende de":

```
┌────────────────────────────────────────────────────────────┐
│ app/main.py — FastAPI + lifespan                            │
│   (crea tablas, carga/reconstruye índices FAISS)            │
└──────────────────────────┬─────────────────────────────────┘
                           │ registra
┌──────────────────────────▼─────────────────────────────────┐
│ routers/v1/  — capa HTTP, prefijo /api/v1                   │
│   machines · work_orders · ingest · chat · admin            │
│   (valida con schemas, delega en services, devuelve JSON)   │
└───────┬──────────────────┬──────────────────┬───────────────┘
        │ usa              │ delega            │ usa
┌───────▼───────────┐ ┌────▼────────────────┐ ┌▼────────────────┐
│ schemas/          │ │ services/           │ │ core/           │
│ contratos Pydantic│ │ qa_service.py       │ │ config, db,     │
│ (validación API)  │ │ (lógica de negocio) │ │ models, log     │
└───────────────────┘ └────┬────────────────┘ └─────────────────┘
                           │ usa
                  ┌────────▼────────────────┐
                  │ library/                │
                  │ embeddings · indexing   │
                  │ faiss_store · storage   │
                  └───┬───────────────┬─────┘
                      ▼               ▼
              PostgreSQL         FAISS (disco)
              (datos, chunks)    (índices por espacio)
```

### 2.2 Dónde vive cada pieza del RAG

| Pieza del RAG | Archivo |
|---|---|
| Extraer texto del archivo (PDF, DOCX, TXT, JSON…) | `library/indexing.py` → `extract_text()` |
| Partir en chunks | `library/indexing.py` → `split_text()` |
| Crear embeddings | `library/embeddings.py` → `embeddings` (OpenAI) |
| Guardar/buscar vectores | `library/faiss_store.py` → índices FAISS |
| Generar la respuesta | `library/embeddings.py` → `qa_chain` (prompt + LLM) |
| Orquestar pregunta→respuesta | `services/qa_service.py` → `answer_question()` |
| Exponerlo por HTTP | `routers/v1/*.py` |

### 2.3 Los tres "espacios" FAISS

Los datos se separan en **espacios** (índices independientes) para que cada
tipo de entidad tenga su propio índice:

- `machines` — una entrada por máquina (texto contextual: nombre, código, ubicación, estado, descripción).
- `work_orders` — una entrada por OT (título, máquina, prioridad, estado, descripción).
- `documents` — los chunks de los archivos subidos (manuales, informes).

Al preguntar se busca en **los tres** y los resultados se **fusionan en un
ranking global** por similitud coseno. Por eso el score es comparable entre
espacios: todos los vectores están normalizados (L2) y se usa producto escalar
= similitud coseno.

> Las máquinas y OTs se indexan como **una sola entrada** (su texto es corto);
> los documentos se parten en **muchos chunks** (pueden ser largos).

### 2.4 Las tablas de la BD y su papel

| Tabla | Papel en el sistema |
|---|---|
| `machines` | Maquinaria registrada (datos estructurados). |
| `work_orders` | Órdenes de trabajo, ligadas a una máquina. |
| `documents` | Metadatos del archivo subido (nombre, a qué entidad va ligado, blob en GCS). |
| `rag_chunks` | **Fuente de verdad del RAG**: texto + embedding + metadata de cada chunk. Permite reconstruir FAISS si se pierde. |
| `chat_sessions` | Sesiones de chat, acotables a máquina/OT. |
| `chat_messages` | Mensajes user/assistant. |
| `citation_logs` | Qué chunks citó cada respuesta y con qué score (para auditar el ranking). |
| `logs_table` | Trazabilidad de eventos (info/error). |

### 2.5 Flujo de INGESTA (subir un documento)

```
POST /api/v1/ingest  (multipart: archivo + machine_id/work_order_id opcional)
        │
        ▼  routers/v1/ingest.py
1. extract_text()   ──► texto plano (PDF, DOCX, TXT, JSON aplanado…)
2. split_text()     ──► chunks de ~1000 chars (solape 200)
3. (opcional) guarda el ORIGINAL en GCS / Firebase Storage
4. embeddings.embed_documents(chunks)  ──► un vector por chunk
5. _index_chunks():  guarda cada chunk en rag_chunks (BD)  +  faiss_store.add()
                     (metadatos: machine_id, work_order_id, document_id…)
        │
        ▼
  201: {document_id, num_chunks, storage_path}
```

### 2.6 Flujo de INDEXACIÓN de máquinas y OTs (automático)

- Al `POST /api/v1/machines` o `/api/v1/work-orders` se genera el **texto
  contextual** (`machine_index_text()` / `work_order_index_text()`) y se
  indexa igual que un documento (pero en su espacio propio).
- Al `PATCH` (actualizar), `reindex_machine()` / `reindex_work_order()`
  comparan el texto indexado nuevo con el viejo:
  - **Si cambió** (estado, prioridad, descripción…): genera el embedding
    **antes** de borrar nada (si OpenAI falla, la transacción se revierte y el
    índice queda intacto), borra los chunks viejos (FAISS + BD) y re-indexa.
  - **Si no cambió**: no llama a OpenAI y devuelve `reindexed: false`.
- La respuesta del PATCH incluye `reindexed` y `num_chunks` para verlo.

### 2.7 Flujo de PREGUNTA (chat)

```
POST /api/v1/chat/sessions            ──► crea sesión (opcional: acotada a máquina/OT)
POST /api/v1/chat/sessions/{id}/messages   {question, top_k, filters}
        │
        ▼  services/qa_service.py → answer_question()
1. Guarda el mensaje del usuario (chat_messages)
2. embeddings.embed_query(question)          ──► vector de la pregunta
3. faiss_store.search() en los 3 espacios    ──► fusiona y ordena por score
   (con filtros: entity_type/id, machine_id, work_order_id)
   + umbral MIN_RELEVANCE_SCORE (0 = off)
4. Contexto = top_k chunks  " [Fuente: nombre]\ncontenido … "
5. qa_chain.invoke({context, question})      ──► respuesta del LLM
6. Guarda respuesta + CitationLog por chunk citado (con su score)
7. Si la sesión no tenía título, usa la pregunta
        │
        ▼
  {message_id, answer, sources: [{name, content, score, entity…}]}
```

**Dato importante:** la sesión sirve para *acotar* la búsqueda (ámbito de
entidad) y para guardar el historial, pero el LLM **no recibe el historial**
como contexto: cada pregunta se responde con los chunks recuperados en ese
momento. Es un diseño intencional (QA sobre documentos), no un chat
conversacional de memoria larga.

### 2.8 El prompt (cómo se "obliga" al modelo a usar el contexto)

En `library/embeddings.py` hay un `ChatPromptTemplate` con un system prompt que
dice, en esencia:

> Eres un asistente experto en mantenimiento industrial (CMMS). Responde a la
> pregunta usando **SOLO el contexto** proporcionado… Si no encuentras la
> respuesta, dilo claramente y **no inventes**. Cuando uses una fuente,
> menciónala entre corchetes, p. ej. `[Bomba centrífuga P-101]`.

Ese "solo usa el contexto" es lo que convierte al LLM en un experto de **tu**
dominio y evita alucinaciones (aunque no las elimina del todo: por eso están
las fuentes).

---

## 3. Recorrido de punta a punta (con curl)

```bash
# 1) Registrar una máquina → se indexa en el espacio "machines"
curl -X POST http://localhost:8000/api/v1/machines \
  -H "Content-Type: application/json" \
  -d '{"code":"P-101","name":"Bomba centrífuga","description":"Bomba de proceso de 30 HP","location":"Planta A"}'

# 2) Crear una OT sobre esa máquina → espacio "work_orders"
curl -X POST http://localhost:8000/api/v1/work-orders \
  -H "Content-Type: application/json" \
  -d '{"machine_id":1,"title":"Cambio de rodamientos","description":"Ruido en el eje al arrancar","priority":"high"}'

# 3) Subir un manual → espacio "documents" (muchos chunks)
curl -F "file=@manual_bomba.pdf" -F "machine_id=1" http://localhost:8000/api/v1/ingest

# 4) Sesión de chat acotada a la máquina
curl -X POST http://localhost:8000/api/v1/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{"entity_type":"machine","entity_id":1,"title":"Diagnóstico P-101"}'

# 5) Preguntar → recupera chunks, genera respuesta, guarda citas
curl -X POST http://localhost:8000/api/v1/chat/sessions/<session_id>/messages \
  -H "Content-Type: application/json" \
  -d '{"question":"¿Qué mantenimiento requiere la bomba P-101?","top_k":5}'
```

En `http://localhost:8000/docs` tienes la documentación interactiva (Swagger)
de cada endpoint con sus schemas.

---

## 4. Qué hicimos en la reorganización

El proyecto estaba con todos los archivos sueltos en `app/` y los endpoints
sin versión (`/machines`, `/ingest`…). Lo reorganizamos en **capas** y
**versionamos la API**:

### Antes

```
app/
├── main.py, config.py, db.py, models.py, schemas.py, log.py,
├── embeddings.py, faiss_store.py, indexing.py, qa_service.py, storage.py
└── routers/  (machines, work_orders, ingest, chat, admin)   ← rutas sin versión
```

### Después

```
app/
├── main.py            # FastAPI + lifespan; registra el api_router v1
├── core/              # Infraestructura: config, db, models (ORM), log
├── schemas/           # Contratos Pydantic por dominio (machine, work_order, ingest, chat, admin)
├── library/           # Motores técnicos: embeddings, faiss_store, indexing, storage
├── services/          # Lógica de negocio: qa_service
└── routers/
    └── v1/            # API versión 1 → prefijo /api/v1
```

Cambios clave:

1. **Core** = lo que no depende de nadie: configuración, motor de BD, modelos
   ORM (la fuente de verdad de los datos) y logging.
2. **Library** = los "motores" del RAG. No saben de reglas de negocio; saben
   *cómo* embeder, partir, buscar vectores y subir blobs.
3. **Services** = casos de uso. `qa_service` orquesta la recuperación +
   generación; los routers quedan delgados.
4. **Schemas** = dividido por dominio para que cada router importe solo lo
   suyo; `__init__.py` re-exporta todo.
5. **Versionado v1** = todos los endpoints bajo `/api/v1`. El prefijo se
   aplica una sola vez en `routers/v1/__init__.py`; para crear una v2 se copia
   la carpeta y se registra el nuevo `api_router` en `main.py`.
6. **READMEs por carpeta** = cada capa explica su funcionalidad para estudiar
   el código por partes.
7. `GET /health` quedó fuera de versiones (check de infraestructura).

> **Compatibilidad:** los clientes que usaban rutas sin versión deben pasar a
> `/api/v1/...`.

---

## 5. Experimentos para seguir aprendiendo

Prueba estos cambios y observa cómo cambia la calidad de las respuestas:

| Experimento | Dónde | Qué observar |
|---|---|---|
| Subir `TOP_K` (p. ej. 10) | `.env` / `config.py` | Más contexto → respuestas más completas, pero más tokens. |
| Activar `MIN_RELEVANCE_SCORE` (p. ej. 0.5) | `.env` | Descarta chunks poco relevantes → menos ruido, pero puede quedarse sin contexto. |
| Filtrar por entidad en la pregunta | `filters` del body | La búsqueda se acota al metadata de esa máquina/OT. |
| Bajar `CHUNK_SIZE` | `.env` | Chunks más pequeños → recuperación más fina, más entradas en el índice. |
| Preguntar algo que no esté en los datos | chat | Verás cómo el prompt "no inventes" responde que no lo sabe. |
| Consultar `citation_logs` | BD | Verás qué chunks alimentaron cada respuesta y su score. |

Siguientes niveles (cuando domines lo básico):

- **Reranker** (p. ej. Cohere): reordenar los top_k recuperados con un modelo
  específico de relevancia (el README raíz ya lo menciona).
- **IndexHNSWFlat** en FAISS: búsqueda aproximada, mucho más rápida con miles
  de chunks.
- **Streaming** de la respuesta y **memoria conversacional** (pasar el
  historial al prompt).
- **Autenticación** en los endpoints (hoy todo está abierto).

---

## 6. La parte de los datos: el 80%

> *"Un sistema de IA es 20% modelo y 80% datos."* — es una heurística, no una
> ley, pero en RAG es muy cierta: el modelo casi no cambia (gpt-4o-mini vs.
> gpt-4o) comparado con lo que cambia **lo que le das a recuperar**.

En un RAG, el 80% de la calidad está en la **tubería de datos**, no en el LLM.
Lo que tú controlas es: qué documentos entran, cómo se parten, qué metadata
llevan, cómo se buscan y cómo se evalúa. El modelo es solo el "cerebro que lee";
los datos son lo que sabe.

### 6.1 Dónde viven los datos en este proyecto

| Dato | Archivo | Decisión que se tomó |
|---|---|---|
| Texto a embeker de máquinas | `library/indexing.py` → `machine_index_text()` | Se embebe **texto contextual** ("MAQUINARIA: nombre (código) · Ubicación · Estado · descripción"), no campos sueltos. |
| Texto a embeker de OTs | `library/indexing.py` → `work_order_index_text()` | Igual: título + máquina + prioridad + estado + descripción. |
| Chunks de documentos | `split_text()` (`chunk_size=1000`, `overlap=200`) | Parte el texto en fragmentos con solape para no cortar ideas por la mitad. |
| Metadata por chunk | `_chunk_metadata()` | `entity_type`, `entity_id`, `machine_id`, `work_order_id`, `document_id` → permite **filtrar la búsqueda por entidad**. |
| Embeddings | `library/embeddings.py` | Modelo `text-embedding-3-small` (OpenAI). |
| Índice vectorial | `library/faiss_store.py` | Un espacio por tipo de entidad (`machines`, `work_orders`, `documents`). |
| Fuente de verdad | `rag_chunks` (BD) | Texto + embedding + metadata en Postgres; FAISS se **reconstruye desde aquí**. |
| Ranking | `services/qa_service.py` + `faiss_store.search()` | Similitud coseno + `top_k` + umbral `MIN_RELEVANCE_SCORE`. |
| Trazabilidad | `citation_logs` | Qué chunks citó cada respuesta y con qué score. |

### 6.2 ¿Tiene lógica cómo manipulamos los datos? Sí, y estas son las decisiones fuertes

1. **Indexar texto contextual, no campos sueltos.** Un embedding de
   `"P-101"` solo no significa nada; `"MAQUINARIA: Bomba centrífuga (código:
   P-101) · Estado: maintenance"` significa mucho más. Es una técnica llamada
   *contextual embedding*: el embedding captura el significado del texto *en
   contexto*. Por eso las búsquedas por concepto funcionan.

2. **Espacios separados por entidad + metadata para filtrar.** Las máquinas y
   OTs son textos cortos (una entrada); los documentos son largos (muchos
   chunks). Separarlos evita que un manual gigante tape a una máquina, y los
   metadatos permiten acotar: *"solo busca en la bomba P-101"*.

3. **`rag_chunks` como fuente de verdad y FAISS como artefacto derivado.** Si
   el índice se corrompe, se regenera desde la BD. Esto es exactamente la
   práctica correcta: el estado canónico en un sitio, los índices se
   reconstruyen.

### 6.3 Lo que falta para aprovechar mejor el "80%"

Estas son las mejoras de **datos** con más impacto (en orden):

| Mejora | Qué es | Impacto |
|---|---|---|
| **Evaluación (golden set)** | Un conjunto de preguntas reales con respuestas esperadas y fuentes correctas. Medir recall/precisión con cada cambio. | El más grande: sin medir, no sabes si estás mejorando. |
| **Limpieza/desduplicación** | Quitar OCR sucio, firmas, páginas de portada, duplicados antes de indexar. | Reduce ruido que contamina el ranking. |
| **Chunking semántico** | Partir por párrafos/secciones con sentido, no por caracteres ciegos. | Chunks más coherentes → mejores recuperaciones. |
| **Búsqueda híbrida** (BM25 + vectores) | Combina coincidencia léxica (códigos, IDs, "P-101") con semántica. | Los códigos exactos son un caso clásico donde el vector solo falla. |
| **Reranker** | Un segundo modelo reordena los top_k recuperados por relevancia real. | El salto de calidad más notorio cuando hay volumen. |
| **Feedback de usuarios** | Votar si la respuesta fue útil y guardarlo. | Alimenta el golden set y detecta huecos de datos. |

> La lección: en este proyecto el modelo (20%) ya está resuelto con una
> configuración sana. El músculo para crecer está en los datos (80%): evaluar,
> limpiar y afinar la recuperación.

## 7. Hoja de ruta para aprender AI Engineering

Un camino ordenado, usando este proyecto como laboratorio:

### Fase 1 — Fundamentos (ya la estás viviendo)
- Cómo funciona un LLM por dentro: tokens, contexto, temperatura, alucinaciones.
- Embeddings y similitud (coseno, distancia).
- RAG básico: chunking → indexado → recuperación → generación (este proyecto).
- Prompt engineering: system prompt, few-shot, formato de salida.

### Fase 2 — Calidad de recuperación (el 80%)
- **Evaluar**: crear un golden set y medir con métricas de RAG (precision@k,
  recall@k, faithfulness; herramientas: RAGAS).
- Búsqueda híbrida (BM25 + vector) y fusión (RRF).
- Rerankers (Cohere, BGE).
- Chunking avanzado y contextual embeddings.
- Fine-tuning de embeddings para tu dominio.

### Fase 3 — Producción
- Observabilidad: tracing de cada pregunta (qué recuperó, qué respondió,
  cuánto tardó, cuánto costó). LangSmith o logs estructurados.
- Versionado: prompts, configs y datos versionados; CI que re-evalúa con el
  golden set antes de desplegar.
- Costos y latencia: caché de preguntas repetidas, modelos baratos primero,
  streaming.
- Seguridad: autenticación, rate limiting, PII en los datos indexados.

### Fase 4 — Más allá del RAG básico
- **Agentes**: darle al modelo herramientas (buscar en BD, llamar APIs) y
  dejar que decida cuándo usarlas.
- **Fine-tuning vs RAG**: cuándo conviene entrenar el modelo con tus datos y
  cuándo seguir con RAG (pista: casi siempre RAG primero).
- **Structured output**: hacer que el LLM devuelva JSON validado (ya lo haces
  con los schemas de salida de los endpoints).

## Índice de archivos clave

| Para aprender sobre… | Lee |
|---|---|
| Conceptos RAG aplicados | `docs/MANUAL.md` (este archivo) |
| Configuración y variables | `app/core/config.py` + README raíz |
| Modelos / BD | `app/core/models.py` |
| Extracción y chunking | `app/library/indexing.py` |
| Embeddings y prompt | `app/library/embeddings.py` |
| Búsqueda vectorial | `app/library/faiss_store.py` |
| Flujo pregunta→respuesta | `app/services/qa_service.py` |
| Endpoints | `app/routers/v1/` + `docs/AUDITORIA.md` |
