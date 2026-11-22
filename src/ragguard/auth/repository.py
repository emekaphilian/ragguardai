"""Session and tenant-membership persistence for human authentication."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from threading import RLock

from ragguard.persistence.database import connect, selected_persistence_backend


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class InMemoryAuthRepository:
    """Test/local adapter. Production OIDC is required to use PostgreSQL."""

    def __init__(self):
        self._lock = RLock()
        self._flows: dict[str, dict] = {}
        self._sessions: dict[str, dict] = {}
        self._memberships: dict[tuple[str, str, str], tuple[str, ...]] = {}
        self._application_memberships: dict[
            tuple[str, str, str, str, str], tuple[str, ...]
        ] = {}
        self._admin_bootstrap_complete = False

    def save_flow(self, state: str, record: dict) -> None:
        with self._lock:
            self._flows[digest(state)] = record

    def consume_flow(self, state: str) -> dict | None:
        with self._lock:
            return self._flows.pop(digest(state), None)

    def save_session(self, session_id: str, record: dict) -> None:
        with self._lock:
            self._sessions[digest(session_id)] = record

    def get_session(self, session_id: str) -> dict | None:
        with self._lock:
            record = self._sessions.get(digest(session_id))
            if not record or record["expires_at"] <= datetime.now(timezone.utc):
                self._sessions.pop(digest(session_id), None)
                return None
            return dict(record)

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(digest(session_id), None)

    def grant_membership(self, issuer: str, subject: str, tenant_id: str, roles: tuple[str, ...]) -> None:
        with self._lock:
            self._memberships[(issuer, subject, tenant_id)] = roles

    def get_membership(self, issuer: str, subject: str, tenant_id: str) -> tuple[str, ...] | None:
        with self._lock:
            return self._memberships.get((issuer, subject, tenant_id))

    def revoke_membership(self, issuer: str, subject: str, tenant_id: str) -> None:
        with self._lock:
            self._memberships.pop((issuer, subject, tenant_id), None)

    def bootstrap_admin_once(self, issuer: str, subject: str, tenant_id: str) -> bool:
        with self._lock:
            if self._admin_bootstrap_complete:
                return False
            self._memberships.setdefault(
                (issuer, subject, tenant_id),
                ("admin",),
            )
            self._admin_bootstrap_complete = True
            return True

    def list_memberships(self, tenant_id: str) -> list[dict]:
        with self._lock:
            return [
                {"issuer": issuer, "subject": subject, "tenant_id": tenant, "roles": list(roles)}
                for (issuer, subject, tenant), roles in self._memberships.items()
                if tenant == tenant_id
            ]

    def grant_application_membership(
        self,
        issuer: str,
        subject: str,
        tenant_id: str,
        application_id: str,
        environment: str,
        roles: tuple[str, ...],
    ) -> None:
        key = (issuer, subject, tenant_id, application_id, environment)
        with self._lock:
            self._application_memberships[key] = tuple(sorted(set(roles)))

    def list_application_memberships(
        self,
        tenant_id: str,
        *,
        issuer: str | None = None,
        subject: str | None = None,
        application_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict]:
        with self._lock:
            memberships = list(self._application_memberships.items())
        result = []
        for (item_issuer, item_subject, item_tenant, item_app, item_environment), roles in memberships:
            if item_tenant != tenant_id:
                continue
            if issuer is not None and item_issuer != issuer:
                continue
            if subject is not None and item_subject != subject:
                continue
            if application_id is not None and item_app != application_id:
                continue
            if environment is not None and item_environment != environment:
                continue
            result.append({
                "issuer": item_issuer,
                "subject": item_subject,
                "tenant_id": item_tenant,
                "application_id": item_app,
                "environment": item_environment,
                "roles": list(roles),
            })
        return sorted(result, key=lambda item: (
            item["application_id"], item["environment"], item["subject"]
        ))

    def revoke_application_membership(
        self,
        issuer: str,
        subject: str,
        tenant_id: str,
        application_id: str,
        environment: str,
    ) -> None:
        key = (issuer, subject, tenant_id, application_id, environment)
        with self._lock:
            self._application_memberships.pop(key, None)


class PostgreSQLAuthRepository:
    """PostgreSQL-backed sessions and RAGGuard-owned tenant permissions."""

    def __init__(self, database_url: str | None = None, *, connection_factory=None):
        self._database_url = database_url
        self._connection_factory = connection_factory

    def _connect(self):
        return self._connection_factory() if self._connection_factory else connect(self._database_url)

    def save_flow(self, state: str, record: dict) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO oidc_login_flows (state_hash, nonce, code_verifier, return_to, expires_at) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (state_hash) DO UPDATE SET "
                "nonce=EXCLUDED.nonce, code_verifier=EXCLUDED.code_verifier, "
                "return_to=EXCLUDED.return_to, expires_at=EXCLUDED.expires_at",
                (digest(state), record["nonce"], record["code_verifier"], record["return_to"], record["expires_at"]),
            )

    def consume_flow(self, state: str) -> dict | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM oidc_login_flows WHERE state_hash=%s AND expires_at > now() "
                "RETURNING nonce, code_verifier, return_to, expires_at",
                (digest(state),),
            )
            row = cursor.fetchone()
        return ({"nonce": row[0], "code_verifier": row[1], "return_to": row[2], "expires_at": row[3]}
                if row else None)

    def save_session(self, session_id: str, record: dict) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO auth_sessions (session_hash, issuer, subject, csrf_hash, expires_at) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (session_hash) DO UPDATE SET "
                "issuer=EXCLUDED.issuer, subject=EXCLUDED.subject, csrf_hash=EXCLUDED.csrf_hash, expires_at=EXCLUDED.expires_at",
                (digest(session_id), record["issuer"], record["subject"], record["csrf_hash"], record["expires_at"]),
            )

    def get_session(self, session_id: str) -> dict | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT issuer, subject, csrf_hash, expires_at FROM auth_sessions "
                "WHERE session_hash=%s AND expires_at > now()",
                (digest(session_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return {"issuer": row[0], "subject": row[1], "csrf_hash": row[2], "expires_at": row[3]}

    def delete_session(self, session_id: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM auth_sessions WHERE session_hash=%s", (digest(session_id),))

    def grant_membership(self, issuer: str, subject: str, tenant_id: str, roles: tuple[str, ...]) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenant_memberships (issuer, subject, tenant_id, roles) VALUES (%s,%s,%s,%s::jsonb) "
                "ON CONFLICT (issuer, subject, tenant_id) DO UPDATE SET roles=EXCLUDED.roles",
                (issuer, subject, tenant_id, json.dumps(sorted(set(roles)))),
            )

    def get_membership(self, issuer: str, subject: str, tenant_id: str) -> tuple[str, ...] | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT roles FROM tenant_memberships WHERE issuer=%s AND subject=%s AND tenant_id=%s",
                (issuer, subject, tenant_id),
            )
            row = cursor.fetchone()
        if not row:
            return None
        roles = row[0] if isinstance(row[0], (list, tuple)) else json.loads(row[0])
        return tuple(roles)

    def revoke_membership(self, issuer: str, subject: str, tenant_id: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM tenant_memberships WHERE issuer=%s AND subject=%s AND tenant_id=%s",
                (issuer, subject, tenant_id),
            )

    def bootstrap_admin_once(self, issuer: str, subject: str, tenant_id: str) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO auth_bootstrap_state (bootstrap_key) "
                "VALUES ('oidc_admin') ON CONFLICT (bootstrap_key) DO NOTHING "
                "RETURNING bootstrap_key"
            )
            if cursor.fetchone() is None:
                return False
            cursor.execute(
                "INSERT INTO tenant_memberships (issuer, subject, tenant_id, roles) "
                "VALUES (%s, %s, %s, '[\"admin\"]'::jsonb) "
                "ON CONFLICT (issuer, subject, tenant_id) DO NOTHING",
                (issuer, subject, tenant_id),
            )
            return True

    def list_memberships(self, tenant_id: str) -> list[dict]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT issuer, subject, roles FROM tenant_memberships WHERE tenant_id=%s ORDER BY subject",
                (tenant_id,),
            )
            rows = cursor.fetchall()
        return [
            {"issuer": row[0], "subject": row[1], "tenant_id": tenant_id,
             "roles": row[2] if isinstance(row[2], (list, tuple)) else json.loads(row[2])}
            for row in rows
        ]

    def grant_application_membership(
        self,
        issuer: str,
        subject: str,
        tenant_id: str,
        application_id: str,
        environment: str,
        roles: tuple[str, ...],
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO application_memberships "
                "(issuer, subject, ragguard_tenant_id, application_id, environment, roles) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb) "
                "ON CONFLICT (issuer, subject, ragguard_tenant_id, application_id, environment) "
                "DO UPDATE SET roles=EXCLUDED.roles, updated_at=now()",
                (
                    issuer,
                    subject,
                    tenant_id,
                    application_id,
                    environment,
                    json.dumps(sorted(set(roles))),
                ),
            )

    def list_application_memberships(
        self,
        tenant_id: str,
        *,
        issuer: str | None = None,
        subject: str | None = None,
        application_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict]:
        filters = ["ragguard_tenant_id=%s"]
        parameters: list[str] = [tenant_id]
        for column, value in (
            ("issuer", issuer),
            ("subject", subject),
            ("application_id", application_id),
            ("environment", environment),
        ):
            if value is not None:
                filters.append(f"{column}=%s")
                parameters.append(value)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT issuer, subject, ragguard_tenant_id, application_id, "
                "environment, roles FROM application_memberships WHERE "
                + " AND ".join(filters)
                + " ORDER BY application_id, environment, subject",
                tuple(parameters),
            )
            rows = cursor.fetchall()
        return [
            {
                "issuer": row[0],
                "subject": row[1],
                "tenant_id": row[2],
                "application_id": row[3],
                "environment": row[4],
                "roles": row[5] if isinstance(row[5], (list, tuple)) else json.loads(row[5]),
            }
            for row in rows
        ]

    def revoke_application_membership(
        self,
        issuer: str,
        subject: str,
        tenant_id: str,
        application_id: str,
        environment: str,
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM application_memberships WHERE issuer=%s AND subject=%s "
                "AND ragguard_tenant_id=%s AND application_id=%s AND environment=%s",
                (issuer, subject, tenant_id, application_id, environment),
            )


def create_auth_repository(*, backend: str | None = None, database_url: str | None = None):
    selected = selected_persistence_backend(backend)
    if selected in {"memory", "inmemory", "in-memory"}:
        return InMemoryAuthRepository()
    if selected in {"postgres", "postgresql"}:
        if not (database_url or os.getenv("RAGGUARD_DATABASE_URL")):
            raise ValueError("RAGGUARD_DATABASE_URL is required for PostgreSQL authentication storage.")
        return PostgreSQLAuthRepository(database_url)
    raise ValueError(f"Unsupported authentication storage backend: {selected}")
