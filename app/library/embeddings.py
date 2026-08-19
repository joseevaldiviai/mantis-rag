from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from ..core.config import settings

embeddings = OpenAIEmbeddings(
    model=settings.embedding_model, api_key=settings.openai_api_key
)

llm = ChatOpenAI(
    model=settings.llm_model, api_key=settings.openai_api_key, temperature=0
)

qa_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Eres un asistente experto en mantenimiento industrial (CMMS). "
            "Responde a la pregunta usando SOLO el contexto proporcionado, que puede "
            "contener información de máquinas, órdenes de trabajo y documentos técnicos. "
            "Si no encuentras la respuesta en el contexto, dilo claramente y no inventes "
            "información. Cuando uses una fuente, menciónala entre corchetes, por "
            "ejemplo [Bomba centrífuga P-101] o [OT #12 - Cambio de rodamientos].\n\n"
            "Contexto:\n{context}",
        ),
        ("human", "Pregunta: {question}"),
    ]
)

# Cadena RAG: prompt -> LLM -> texto plano
qa_chain = qa_prompt | llm | StrOutputParser()
