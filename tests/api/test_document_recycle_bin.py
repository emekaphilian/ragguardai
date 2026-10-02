from pathlib import Path

from ragguard.api.runtime import Workspace
from ragguard.auth.tenant_context import TenantContext


def context(tenant_id="development"):
    return TenantContext(
        tenant_id=tenant_id,
        application_id="app-a",
        environment="production",
        user_id=None,
        roles=(),
        vector_namespace=tenant_id,
        policy_version="v1",
        index_version="v1",
    )


def test_deleted_source_document_stays_out_of_index_until_restored(tmp_path: Path):
    raw = tmp_path / "raw"
    recycle = tmp_path / "recycle_bin"
    raw.mkdir()
    source = raw / "pricing.txt"
    source.write_text("Premium plan costs forty dollars monthly.", encoding="utf-8")

    workspace = Workspace(raw_directory=raw, recycle_directory=recycle)
    assert [row["id"] for row in workspace.document_rows(context())] == ["pricing"]

    assert workspace.delete_document("pricing", context())
    assert not source.exists()
    assert workspace.document_rows(context()) == []
    assert workspace.query("premium plan price", context=context())["sources"] == []
    assert workspace.recycled_document_rows(context())[0]["id"] == "pricing"

    restarted = Workspace(raw_directory=raw, recycle_directory=recycle)
    assert restarted.document_rows(context()) == []
    assert restarted.recycled_document_rows(context())[0]["id"] == "pricing"

    assert restarted.restore_document("pricing", context())
    assert source.exists()
    assert [row["id"] for row in restarted.document_rows(context())] == ["pricing"]

    assert restarted.delete_document("pricing", context())
    assert restarted.permanently_delete_document("pricing", context())
    final_restart = Workspace(raw_directory=raw, recycle_directory=recycle)
    assert final_restart.document_rows(context()) == []
    assert final_restart.recycled_document_rows(context()) == []


def test_recycle_bin_operations_cannot_cross_tenant_boundaries(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "private.txt").write_text("Tenant private material.", encoding="utf-8")
    workspace = Workspace(raw_directory=raw, recycle_directory=tmp_path / "recycle_bin")

    assert not workspace.delete_document("private", context("tenant-b"))
    assert workspace.document_rows(context())[0]["id"] == "private"

    assert workspace.delete_document("private", context())
    assert workspace.recycled_document_rows(context("tenant-b")) == []
    assert not workspace.restore_document("private", context("tenant-b"))
    assert not workspace.permanently_delete_document("private", context("tenant-b"))
