from __future__ import annotations

import os
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Callable

ConnectionFactory = Callable[[], AbstractContextManager[Any]]


def connect(database_url: str | None = None):
    """Open a PostgreSQL connection using the optional psycopg driver."""
    dsn = database_url or os.getenv("RAGGUARD_DATABASE_URL")
    if not dsn:
        raise ValueError("RAGGUARD_DATABASE_URL must be configured for PostgreSQL audit storage.")

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Install the PostgreSQL extra to use PostgreSQL audit storage."
        ) from exc

    return psycopg.connect(dsn)


def apply_migrations(
    *,
    database_url: str | None = None,
    connection_factory: ConnectionFactory | None = None,
    migrations_dir: Path | None = None,
) -> None:
    """Apply idempotent SQL migrations in filename order."""
    factory = connection_factory or (lambda: connect(database_url))
    directory = migrations_dir or Path(__file__).with_name("migrations")

    for migration in sorted(directory.glob("*.sql")):
        with factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(migration.read_text(encoding="utf-8"))
