import pytest

from ragguard.config import load_settings


def test_development_config_does_not_implicitly_enable_headers(monkeypatch):
    monkeypatch.delenv("RAGGUARD_AUTH_MODE", raising=False)
    settings = load_settings("configs/development.yaml")
    assert settings.authentication.mode == "disabled"


def test_development_headers_require_explicit_mode(monkeypatch):
    monkeypatch.setenv("RAGGUARD_AUTH_MODE", "development_headers")
    monkeypatch.setenv("RAGGUARD_ENV", "development")
    settings = load_settings("configs/development.yaml")
    assert settings.authentication.mode == "development_headers"


def test_environment_auth_mode_overrides_config(monkeypatch):
    monkeypatch.setenv("RAGGUARD_AUTH_MODE", "disabled")
    settings = load_settings("configs/development.yaml")
    assert settings.authentication.mode == "disabled"


def test_production_cannot_enable_development_headers(monkeypatch):
    monkeypatch.setenv("RAGGUARD_AUTH_MODE", "development_headers")
    monkeypatch.setenv("RAGGUARD_ENV", "production")
    with pytest.raises(ValueError, match="restricted to development and tests"):
        load_settings("configs/development.yaml")


def test_unknown_auth_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("RAGGUARD_AUTH_MODE", "accept-any-header")
    with pytest.raises(ValueError, match="Unsupported RAGGUARD_AUTH_MODE"):
        load_settings("configs/development.yaml")
