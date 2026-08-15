from __future__ import annotations

import traceback

from .db import SessionLocal
from .models import LogEntry


def log_event(
    level: str,
    event_message: str,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    exc: BaseException | None = None,
) -> None:
    """Escribe un evento en logs_table. Nunca debe romper el flujo principal."""
    try:
        with SessionLocal() as session:
            session.add(
                LogEntry(
                    level=level,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    event_message=event_message,
                    traceback="".join(traceback.format_exception(exc)) if exc else None,
                )
            )
            session.commit()
    except Exception:
        pass
