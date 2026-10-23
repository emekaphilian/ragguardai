"""Authentication adapter contract and local-only development provider."""
from __future__ import annotations

from typing import Protocol

from fastapi import Request

from ragguard.config import Settings

from .principal import AuthenticationError, AuthenticationUnavailable, VerifiedPrincipal


class PrincipalAuthenticator(Protocol):
    def authenticate(self, request: Request, settings: Settings) -> VerifiedPrincipal:
        """Verify the request and return its normalized principal."""


class DevelopmentHeaderAuthenticator:
    """Accept caller identity headers only in explicitly enabled local/test mode."""

    def authenticate(self, request: Request, settings: Settings) -> VerifiedPrincipal:
        if settings.authentication.mode != "development_headers":
            raise AuthenticationUnavailable("Development-header authentication is disabled.")
        if settings.environment.lower() not in {"development", "testing"}:
            raise AuthenticationUnavailable(
                "Development-header authentication is restricted to development and tests."
            )

        subject = request.headers.get("X-RAGGuard-User", "local-developer").strip()
        if not subject:
            raise AuthenticationError("A development subject is required.")
        roles = tuple(
            role.strip()
            for role in request.headers.get("X-RAGGuard-Roles", "").split(",")
            if role.strip()
        )
        return VerifiedPrincipal(
            issuer="urn:ragguard:development",
            subject=subject,
            roles=roles,
            authentication_method="development_headers",
        )


def authenticate_principal(request: Request, settings: Settings) -> VerifiedPrincipal:
    mode = settings.authentication.mode
    if mode == "development_headers":
        return DevelopmentHeaderAuthenticator().authenticate(request, settings)
    if mode == "disabled":
        raise AuthenticationUnavailable("Human-user authentication is not configured.")
    if mode == "oidc":
        raise AuthenticationUnavailable("OIDC authentication has not been configured yet.")
    if mode == "trusted_proxy":
        raise AuthenticationUnavailable("Trusted-proxy authentication has not been configured yet.")
    raise AuthenticationUnavailable("No authentication provider is configured.")
