"""Explicitly opt the test suite into its isolated development identities."""
import os


os.environ.setdefault("RAGGUARD_AUTH_MODE", "development_headers")
os.environ.setdefault("RAGGUARD_ENV", "testing")
