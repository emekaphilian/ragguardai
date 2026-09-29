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
