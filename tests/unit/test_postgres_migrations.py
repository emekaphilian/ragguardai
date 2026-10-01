import asyncio
import importlib

from ragguard.persistence.database import apply_migrations


def test_migrations_run_in_lexical_order(tmp_path):
    (tmp_path / "0002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "0001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    executed = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql):
            executed.append(sql)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return Cursor()

    apply_migrations(
        connection_factory=Connection,
        migrations_dir=tmp_path,
    )

    assert executed == ["SELECT 1;", "SELECT 2;"]


def test_api_startup_applies_migrations_for_postgres(monkeypatch):
    app_module = importlib.import_module("ragguard.api.app")
    calls = []
    monkeypatch.setenv("RAGGUARD_AUDIT_BACKEND", "postgres")
    monkeypatch.setattr(app_module, "apply_migrations", lambda: calls.append(True))

    async def enter_and_exit_lifespan():
        async with app_module.app.router.lifespan_context(app_module.app):
            pass

    asyncio.run(enter_and_exit_lifespan())

    assert calls == [True]
