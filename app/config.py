from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openai_api_key: str = ""
    database_url: str = "postgresql+psycopg2://rag:rag@localhost:5432/rag"

    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"

    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Búsqueda vectorial
    top_k: int = 5                 # chunks finales que entran en el contexto
    min_relevance_score: float = 0.0  # 0 = desactivado; sube el umbral para afinar

    # FAISS: directorio donde se persisten los índices y los "espacios" por entidad
    faiss_index_dir: str = "data/faiss"
    faiss_spaces: list[str] = ["machines", "work_orders", "documents"]

    # Almacenamiento del archivo original (Firebase Storage / GCS).
    # Si gcs_bucket está vacío, el original NO se guarda: solo se indexan los chunks.
    gcs_bucket: str = ""
    # Ruta al JSON de la service account, o contenido del JSON directamente.
    gcs_credentials: str = ""
    gcs_credentials_json: str = ""


settings = Settings()
