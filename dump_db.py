#!/usr/bin/env python3
"""Genera un dump de la base de datos del CMMS RAG.

Por defecto escribe un archivo SQL reimportable (CREATE TABLE + INSERT) en
`dumps/`. Con `--format json` genera un archivo JSON con una colección por
tabla, pensado para subir a Firestore (Firebase es NoSQL: no acepta SQL).

Uso:
    python dump_db.py                                # dump SQL completo
    python dump_db.py --format json                  # JSON (colecciones por tabla)
    python dump_db.py --tables machines,work_orders  # solo esas tablas
    python dump_db.py --schema-only                  # solo el esquema (CREATE TABLE)
    python dump_db.py --data-only                    # solo los datos (INSERT)
    python dump_db.py --output backup.sql            # ruta de salida
    python dump_db.py --db-url postgresql+psycopg2://user:pass@host:5432/db

Dentro del contenedor Docker:
    docker compose exec api python dump_db.py
    docker compose cp api:/app/dumps/<archivo>.sql .
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.core import models  # noqa: F401  # registra los modelos en Base.metadata
from app.core.config import settings
from app.core.db import Base

INSERT_BATCH = 100  # filas por sentencia INSERT


def sql_literal(value) -> str:
    """Convierte un valor Python en un literal SQL válido para Postgres."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, uuid.UUID):
        return f"'{value}'"
    if isinstance(value, (datetime, date)):
        return f"'{value.isoformat()}'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, dict):  # jsonb
        raw = json.dumps(value, ensure_ascii=False, default=str).replace("'", "''")
        return f"'{raw}'::jsonb"
    if isinstance(value, (list, tuple)):  # embedding (ARRAY(Float))
        items = ", ".join(repr(float(v)) for v in value)
        return f"ARRAY[{items}]::float8[]"
    raise TypeError(f"Tipo no soportado en el dump: {type(value)}")


def table_ddl(table) -> str:
    """CREATE TABLE IF NOT EXISTS para una tabla, en el orden de dependencias."""
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    return ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1) + ";"


def table_inserts(table, rows) -> str:
    """Sentencia(s) INSERT con los valores de `rows`."""
    cols = ", ".join(f'"{c.name}"' for c in table.columns)
    stmts = []
    for i in range(0, len(rows), INSERT_BATCH):
        batch = rows[i : i + INSERT_BATCH]
        values = ",\n".join(
            "(" + ", ".join(sql_literal(r[c.name]) for c in table.columns) + ")"
            for r in batch
        )
        stmts.append(f'INSERT INTO "{table.name}" ({cols}) VALUES\n{values};')
    return "\n".join(stmts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db-url", default=settings.database_url, help="URL de conexión")
    parser.add_argument("--format", choices=["sql", "json"], default="sql")
    parser.add_argument("--output", help="ruta de salida (defecto: dumps/dump_<fecha>.<ext>)")
    parser.add_argument("--tables", help="solo estas tablas, separadas por coma")
    parser.add_argument("--schema-only", action="store_true", help="solo CREATE TABLE")
    parser.add_argument("--data-only", action="store_true", help="solo INSERT")
    args = parser.parse_args()

    if args.schema_only and args.data_only:
        parser.error("--schema-only y --data-only son excluyentes")

    tables = list(Base.metadata.sorted_tables)  # orden topológico por FKs
    if args.tables:
        names = {n.strip() for n in args.tables.split(",") if n.strip()}
        tables = [t for t in tables if t.name in names]
        missing = names - {t.name for t in tables}
        if missing:
            print(f"ERROR: tablas no encontradas: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    engine = create_engine(args.db_url)
    rows_by_table: dict[str, list] = {}
    with engine.connect() as conn:
        for table in tables:
            result = conn.execute(select(table))
            rows_by_table[table.name] = result.mappings().all()
            print(f"  {table.name}: {len(rows_by_table[table.name])} filas")

    if args.format == "json":
        data = {t.name: [dict(r) for r in rows_by_table[t.name]] for t in tables}
        content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        ext = "json"
    else:
        lines = [
            "-- Dump de la base de datos del CMMS RAG",
            f"-- Generado: {datetime.now().isoformat(timespec='seconds')}",
            "-- Restaurar: psql -U rag -d rag < <archivo>.sql",
            "",
            "BEGIN;",
            "",
        ]
        if not args.data_only:
            # DROP en orden inverso para no romper las FKs
            for table in reversed(tables):
                lines.append(f'DROP TABLE IF EXISTS "{table.name}" CASCADE;')
            lines.append("")
            for table in tables:
                lines.append(table_ddl(table))
            lines.append("")
        if not args.schema_only:
            for table in tables:
                rows = rows_by_table[table.name]
                if rows:
                    lines.append(table_inserts(table, rows))
                    lines.append("")
        lines.append("COMMIT;")
        lines.append("")
        content = "\n".join(lines)
        ext = "sql"

    if args.output:
        out_path = Path(args.output)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path("dumps") / f"dump_{stamp}.{ext}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")

    total = sum(len(rows) for rows in rows_by_table.values())
    print(f"\nOK: {len(tables)} tablas, {total} filas -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
