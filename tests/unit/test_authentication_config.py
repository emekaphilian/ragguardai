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


def test_oidc_settings_are_loaded_from_server_environment(monkeypatch):
    monkeypatch.setenv("RAGGUARD_AUTH_MODE", "oidc")
    monkeypatch.setenv("RAGGUARD_OIDC_ISSUER", "https://issuer.example/")
    monkeypatch.setenv("RAGGUARD_OIDC_CLIENT_ID", "client")
    monkeypatch.setenv("RAGGUARD_OIDC_CLIENT_SECRET", "server-secret")
    monkeypatch.setenv("RAGGUARD_OIDC_TOKEN_AUTH_METHOD", "client_secret_post")
    monkeypatch.setenv("RAGGUARD_OIDC_REDIRECT_URI", "https://api.example/api/v1/auth/callback")
    monkeypatch.setenv("RAGGUARD_FRONTEND_URL", "https://dashboard.example")
    monkeypatch.setenv("RAGGUARD_FRONTEND_ORIGINS", "https://dashboard.example, https://admin.example/")
    monkeypatch.setenv("RAGGUARD_SESSION_SECRET", "s" * 40)
    settings = load_settings("configs/development.yaml").authentication

    assert settings.mode == "oidc"
    assert settings.oidc_issuer == "https://issuer.example/"
    assert settings.session_secret == "s" * 40
    assert settings.oidc_token_auth_method == "client_secret_post"
    assert settings.frontend_origins == ("https://dashboard.example", "https://admin.example")


def test_same_site_none_requires_secure_cookie(monkeypatch):
    monkeypatch.setenv("RAGGUARD_SESSION_COOKIE_SAMESITE", "none")
    monkeypatch.setenv("RAGGUARD_SESSION_COOKIE_SECURE", "false")
    with pytest.raises(ValueError, match="require Secure"):
        load_settings("configs/development.yaml")


def test_wildcard_and_non_https_public_frontend_origins_are_rejected(monkeypatch):
    monkeypatch.setenv("RAGGUARD_FRONTEND_ORIGINS", "*")
    with pytest.raises(ValueError, match="exact HTTPS origins"):
        load_settings("configs/development.yaml")
    monkeypatch.setenv("RAGGUARD_FRONTEND_ORIGINS", "http://dashboard.example.com")
    with pytest.raises(ValueError, match="exact HTTPS origins"):
        load_settings("configs/development.yaml")
