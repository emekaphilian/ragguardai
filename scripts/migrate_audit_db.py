from ragguard.persistence.database import apply_migrations


if __name__ == "__main__":
    apply_migrations()
    print("Recovery audit migrations applied.")
