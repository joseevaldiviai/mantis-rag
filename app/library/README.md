# `app/library/` — Componentes técnicos reutilizables

Capa de **biblioteca técnica**: piezas con una responsabilidad clara y sin
lógica de negocio. Son los "motores" del RAG (embeddings, búsqueda vectorial,
indexación y almacenamiento de archivos) que `services/` y `routers/` utilizan.

| Archivo          | Funcionalidad |
|---|---|
| `embeddings.py`  | Clientes de OpenAI: `embeddings` (modelo de embeddings), `llm` (ChatOpenAI) y `qa_chain` (prompt CMMS → LLM → texto). |
| `faiss_store.py` | Almacén vectorial FAISS con **espacios** (`machines`, `work_orders`, `documents`), persistencia en disco, `search()` multi-espacio con ranking por similitud coseno y `rebuild()` de seguridad. |
| `indexing.py`    | Convierte máquinas, OTs y documentos en **chunks contextuales** (texto + embedding + metadata), los indexa en FAISS y en `rag_chunks`, y re-indexa automáticamente al actualizar una entidad. |
| `storage.py`     | Sube/descarga el archivo original (PDF, DOCX…) a Google Cloud Storage / Firebase Storage. Si no está configurado, degrada con elegancia (solo se indexan chunks). |

## ¿Por qué `library/` y no dentro de `services/`?

`library/` responde a **"¿cómo se hace técnicamente?"** (embeder, partir texto,
buscar vectores, subir blobs) y **no conoce las reglas de negocio**. La lógica
que decide *qué* se indexa, *cuándo* re-indexar o *cómo* responder una pregunta
vive en `services/` (o en los routers).

Ejemplo de uso desde `services/`:

```python
from ..library import faiss_store
from ..library.embeddings import embeddings, qa_chain
```
