# Manual: LangChain y LangGraph

Guía para entender **qué es cada librería**, **en qué se diferencian** y
**cuándo usar cuál**, con ejemplos aplicados a este proyecto (Mantis CMMS RAG).

---

## 1. Primero: el mapa del ecosistema "Lang"

Los nombres confunden porque son de la misma familia (los crea la misma
compañía, LangChain Inc.), pero son **capas distintas** que se usan juntas:

```
┌─────────────────────────────────────────────────────────┐
│  APLICACIÓN (lo que tú construyes)                      │
├─────────────────────────────────────────────────────────┤
│  LangGraph   → runtime de agentes (orquestación con     │
│                estado, ciclos, memoria)                 │
│  LangChain   → framework de componentes (modelos,       │
│                prompts, cadenas, integraciones)         │
├─────────────────────────────────────────────────────────┤
│  LangSmith   → observabilidad (tracing, evaluación)     │
│  LangServe   → desplegar tus cadenas como API           │
└─────────────────────────────────────────────────────────┘
```

| Librería | Rol | Analogía |
|---|---|---|
| **LangChain** | Framework de componentes y cadenas lineales | Los "ladrillos" y el "pegamento" |
| **LangGraph** | Orquestación de agentes/flujos con estado | El "director de orquesta" que decide el orden y repite |
| **LangSmith** | Tracing, evaluación y monitoreo | La "cámara de video" que graba cada ejecución |
| **LangServe** | Convertir cadenas/grafos en API REST | El "restaurante" que sirve lo que cocinas |

> La confusión es normal: en la documentación de LangChain verás a LangGraph
> por todos lados porque, **desde la versión 0.3/1.0, LangGraph es la forma
> recomendada de construir agentes** (el `AgentExecutor` clásico de LangChain
> quedó obsoleto).

---

## 2. LangChain — el framework de componentes

### Qué es

Un framework de código abierto para construir aplicaciones con LLM. Su idea
central: **componer piezas reutilizables** (modelos, prompts, parsers,
retrievers, herramientas) en pipelines, sin escribir integraciones a mano.

### Piezas principales

| Pieza | Qué hace | Ejemplo |
|---|---|---|
| **Modelos** (`langchain-openai`) | LLMs y embeddings de cualquier proveedor con la misma API | `ChatOpenAI`, `OpenAIEmbeddings` |
| **Prompts** (`langchain-core`) | Plantillas de prompt con variables | `ChatPromptTemplate` |
| **Parsers** | Convertir la salida del modelo en algo usable | `StrOutputParser`, `JsonOutputParser` |
| **Cadenas (LCEL)** | Componer piezas con el operador `\|` | `prompt \| llm \| parser` |
| **Splitters** | Partir textos en chunks | `RecursiveCharacterTextSplitter` |
| **Vector stores / retrievers** | Guardar y buscar embeddings | `FAISS`, `similarity_search` |
| **Tools** | Funciones que el modelo puede invocar | calculadora, consulta a BD, API externa |

### Para qué se usa

- **RAG** (como este proyecto): chunking → embeddings → vector store → recuperación → generación.
- Prototipos rápidos y pipelines **lineales** paso a paso.
- Abstraer proveedores: cambiar de OpenAI a Anthropic sin reescribir tu código.

### Ejemplo real de este proyecto

En `app/library/embeddings.py`:

```python
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

embeddings = OpenAIEmbeddings(model=settings.embedding_model)

llm = ChatOpenAI(model=settings.llm_model, temperature=0)

qa_prompt = ChatPromptTemplate.from_messages([
    ("system", "Eres un experto en mantenimiento industrial (CMMS). "
               "Responde usando SOLO el contexto... {context}"),
    ("human", "Pregunta: {question}"),
])

qa_chain = qa_prompt | llm | StrOutputParser()   # ← LCEL: cadena
```

`qa_chain.invoke({"context": ctx, "question": q})` ejecuta los tres pasos en
orden: arma el prompt → llama al LLM → devuelve texto plano.

---

## 3. LangGraph — el runtime de agentes

### Qué es

Un framework para orquestar **flujos complejos con estado** (agentes,
multi-paso, ciclos). En lugar de una cadena lineal, defines un **grafo**: nodos
(funciones) y aristas (transiciones), con un **estado** que viaja entre nodos
y que se puede **persistir** (checkpoints).

### Conceptos clave

| Concepto | Qué es |
|---|---|
| **StateGraph** | El grafo con un esquema de estado (TypedDict). |
| **Nodos** | Funciones que reciben el estado y devuelven actualizaciones. |
| **Aristas** | Transiciones entre nodos. |
| **Aristas condicionales** | El próximo nodo se decide en runtime (p. ej. "si el modelo quiere buscar → nodo buscar; si no → responder"). |
| **Ciclos** | El grafo puede volver a un nodo anterior (¡lo que una cadena lineal no puede!). |
| **Checkpointer** | Persiste el estado por `thread_id` → **memoria entre turnos** (MemorySaver, SqliteSaver, PostgresSaver…). |
| **Interrupt / human-in-the-loop** | Pausar el grafo y pedir aprobación humana antes de continuar. |
| **Subgrafos** | Un grafo dentro de otro (modularidad). |

### Para qué se usa

- **Agentes** que deciden qué herramienta llamar (ReAct: piensa → actúa → observa → repite).
- Flujos **multi-paso** con ramas y condiciones (no lineales).
- **Memoria persistente** entre conversaciones.
- **Aprobación humana** (ejecutar una acción destructiva solo con confirmación).
- RAG avanzado: reescribir la consulta, verificar la respuesta, reintentar si no hay contexto.

### Ejemplo mínimo

```python
from typing import Annotated, TypedDict
import operator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, END, StateGraph


class State(TypedDict):
    messages: Annotated[list, operator.add]  # el estado acumula mensajes


def retrieve(state: State):     # nodo 1
    # busca en FAISS y añade el contexto al estado
    return {"messages": [f"contexto: ..."]}


def answer(state: State):       # nodo 2
    # genera la respuesta con el contexto
    return {"messages": [qa_chain.invoke(state["messages"])]}


builder = StateGraph(State)
builder.add_node("retrieve", retrieve)
builder.add_node("answer", answer)
builder.add_edge(START, "retrieve")
builder.add_edge("retrieve", "answer")
builder.add_edge("answer", END)

app = builder.compile(checkpointer=MemorySaver())

result = app.invoke(
    {"messages": [pregunta]},
    config={"configurable": {"thread_id": "sesion-1"}},  # memoria por sesión
)
```

Fíjate en lo que LangGraph aporta sobre LangChain: **estado que fluye, orden
que tú defines, memoria por `thread_id` y la posibilidad de ciclos** (aquí no
hay, pero un agente ReAct volvería a "retrieve" las veces que haga falta).

---

## 4. Diferencias clave (resumen)

| Aspecto | LangChain | LangGraph |
|---|---|---|
| **Modelo mental** | Cadena (pipeline) lineal de componentes | Grafo de nodos con estado |
| **Flujo** | Lineal, definido al componer | Cíclico, ramificado, decidido en runtime |
| **Estado** | Implícito (solo pasa de entrada a salida) | Explícito, definido por ti, persistible |
| **Memoria** | No gestiona; la agregas tú | Checkpointers nativos (`thread_id`) |
| **Ciclos / loops** | No (una cadena no vuelve atrás) | Sí (núcleo de los agentes) |
| **Human-in-the-loop** | No | Sí (interrupts) |
| **Mejor para** | RAG simple, prototipos, pipelines lineales | Agentes, flujos multi-paso, workflows con decisión |
| **Relación** | Aporta los componentes | Orquesta los componentes |

**Regla rápida:** LangChain responde *"¿qué piezas uso?"*; LangGraph responde
*"¿en qué orden se ejecutan, se repiten y se deciden?"*.

---

## 5. Cómo se complementan

No es "uno u otro": **LangGraph usa componentes de LangChain**. Tu `qa_chain`,
tus `embeddings`, tu vector store FAISS — todo eso sigue siendo de LangChain;
LangGraph los envuelve en nodos y decide el flujo.

```
              ┌─────────────────────────────┐
              │        LangGraph            │  estado, orden, ciclos, memoria
              └───────┬───────┬───────┬─────┘
                      │       │       │
              ┌───────▼───┐ ┌─▼──────┐ ┌▼──────────┐
              │ qa_chain  │ │FAISS   │ │ ChatOpenAI│   ← componentes LangChain
              │ (LCEL)    │ │search  │ │           │
              └───────────┘ └────────┘ └───────────┘
```

En la práctica: **casi todo proyecto con LangGraph importa cosas de
`langchain_core` / `langchain_openai`**.

---

## 6. Cuándo usar cada uno

**Usa solo LangChain (como este proyecto) cuando:**
- Tu flujo es lineal y predecible: recuperar → generar → responder.
- No necesitas ciclos ni decisiones en runtime.
- Quieres algo simple de leer y depurar.

**Añade LangGraph cuando:**
- El modelo debe **decidir** qué hacer (agente con herramientas).
- Necesitas **repetir** un paso (reintentar búsqueda, loop de verificación).
- Quieres **memoria persistente** entre turnos (checkpointer).
- Necesitas **aprobación humana** antes de una acción.
- El flujo tiene ramas/condiciones (RAG multi-etapa).

**Cuándo ninguno de los dos:**
- Un solo prompt sin pipeline → SDK del proveedor directo.
- Pipelines complejos de datos (ETL pesado) → Airflow/Prefect (no LLM).

---

## 7. En este proyecto: qué usamos y dónde encajaría LangGraph

### Lo que ya usamos de LangChain (y está bien así)

`embeddings.py`, `indexing.py` y `faiss_store.py` usan componentes de
LangChain (modelos, splitter, vector store, LCEL). Para un RAG lineal como
este, **no necesitas LangGraph**: la cadena actual `recuperar → generar` es
exactamente el caso de uso de LangChain solo.

### Dónde LangGraph tendría sentido aquí (ideas concretas)

1. **RAG con reescritura de consulta:** nodo que reescribe la pregunta del
   usuario (jerga CMMS: "la bomba que hace ruido" → "bomba P-101
   rodamientos") *antes* de buscar en FAISS → una arista condicional decide si
   reescribir o buscar directo.
2. **Agente que consulta la BD:** un nodo que ejecuta SQL (p. ej. "muéstrame
   las OTs vencidas") cuando el modelo lo pide, usando `tools` + ciclo ReAct.
3. **Verificación de respuesta:** después de responder, un nodo comprueba si
   la respuesta realmente está soportada por las fuentes; si no, re-busca con
   otros parámetros (ciclo).
4. **Aprobación humana:** p. ej. confirmar antes de `POST /reindex` o de
   borrar entidades (human-in-the-loop con interrupts).

> Este proyecto es tu "laboratorio": podrías crear un segundo endpoint
> `POST /api/v2/chat/sessions/{id}/messages` (recuerda: versionado de la API)
> que use un grafo LangGraph con reescritura de consulta, y comparar la
> calidad con la v1. Eso es exactamente el ciclo "evaluar antes de cambiar".

---

## 8. Ojo con los nombres nuevos (2026)

LangChain sigue evolucionando: en su blog oficial ya hablan de **Deep Agents**
como un *harness* (contenedor de ejecución) que se suma a la distinción
framework vs runtime. No te líes: para lo que necesitas hoy, la combinación
correcta es **componentes de LangChain + orquestación con LangGraph cuando el
flujo lo pida + LangSmith para observar lo que pasa**.

---

## 9. Cómo seguir aprendiendo

1. **En este repo:** lee `app/library/embeddings.py` y `app/library/faiss_store.py`
   y localiza cada pieza de LangChain que usa (modelo, prompt, parser, store).
2. **Haz el mini-proyecto:** un agente con LangGraph que decida entre "buscar
   en FAISS" y "ejecutar SQL" sobre este mismo CMMS.
3. **Documentación oficial:** langchain.com (docs de LangChain, LangGraph y
   LangSmith); el tutorial oficial "Build a ReAct agent" usa LangGraph.
4. **Práctica de evaluación:** cuando tengas un grafo, mide con golden sets
   (ver `docs/MANUAL.md` §6) si la reescritura de consulta mejora el recall.
