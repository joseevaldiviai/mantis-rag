"""Almacenamiento del archivo original en Google Cloud Storage.

Firebase Storage es una capa sobre GCS: cuando creas un proyecto Firebase se
crea un bucket `<proyecto>.appspot.com`. Desde un servidor Python (FastAPI) se
sube con el cliente `google-cloud-storage` contra ese bucket.

Si `GCS_BUCKET` está vacío o las credenciales no son válidas, el sistema se
deglada con elegancia: el original NO se guarda y solo se indexan los chunks
(comportamiento original del proyecto).
"""

from __future__ import annotations

import json
import logging
import uuid

from ..core.config import settings

logger = logging.getLogger(__name__)

_client = None
_bucket = None
_bucket_error: Exception | None = None


def _get_bucket():
    """Devuelve el bucket GCS, o None si no está configurado / hay error."""
    global _client, _bucket, _bucket_error
    if _bucket is not None or _bucket_error is not None:
        return _bucket

    if not settings.gcs_bucket:
        _bucket_error = RuntimeError("GCS_BUCKET no está configurado")
        return None

    try:
        from google.cloud import storage

        if settings.gcs_credentials_json:
            _client = storage.Client.from_service_account_info(
                json.loads(settings.gcs_credentials_json)
            )
        elif settings.gcs_credentials:
            _client = storage.Client.from_service_account_json(settings.gcs_credentials)
        else:
            # ADC (Application Default Credentials): GOOGLE_APPLICATION_CREDENTIALS
            _client = storage.Client()
        _bucket = _client.bucket(settings.gcs_bucket)
        logger.info("Storage GCS configurado: bucket=%s", settings.gcs_bucket)
    except Exception as exc:  # import, credenciales, red…
        _bucket_error = exc
        logger.warning("Storage GCS no disponible (%s): el original no se guardará.", exc)

    return _bucket


def storage_enabled() -> bool:
    return _get_bucket() is not None


def upload_original(
    document_id: uuid.UUID, filename: str, data: bytes, content_type: str
) -> str | None:
    """Sube el archivo original a `documents/{document_id}/{filename}`.

    Devuelve el storage_path (blob) o None si el storage no está disponible.
    """
    bucket = _get_bucket()
    if bucket is None:
        return None

    blob_path = f"documents/{document_id}/{filename}"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
    return blob_path


def download_original(storage_path: str) -> bytes | None:
    """Descarga el archivo original desde GCS. None si no está disponible."""
    bucket = _get_bucket()
    if bucket is None:
        return None
    blob = bucket.blob(storage_path)
    return blob.download_as_bytes()


def signed_url(storage_path: str, expires_in_minutes: int = 60) -> str | None:
    """URL firmada temporal para descargar el original sin hacer el bucket público."""
    bucket = _get_bucket()
    if bucket is None:
        return None
    blob = bucket.blob(storage_path)
    return blob.generate_signed_url(
        version="v4",
        expiration=expires_in_minutes * 60,
        method="GET",
    )
