from ragguard.config import load_settings
from ragguard.observability.retention import RecoveryRetentionService
from ragguard.persistence.repositories import create_recovery_audit_repository


if __name__ == "__main__":
    settings = load_settings()
    repository = create_recovery_audit_repository()
    retention = RecoveryRetentionService(
        repository,
        retention_days=settings.audit_retention_days,
    )
    deleted = retention.delete_by_retention_policy()
    print(f"Deleted {deleted} expired recovery audit records.")
