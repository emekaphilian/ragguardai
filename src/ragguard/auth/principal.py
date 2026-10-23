"""Provider-independent representation of an authenticated human identity."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerifiedPrincipal:
    """Identity facts established by a configured authentication adapter.

    ``issuer`` and ``subject`` form the stable identity key. Instances must be
    created only after an adapter has authenticated the request.
    """

    issuer: str
    subject: str
    roles: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    authentication_method: str = "unknown"


class AuthenticationError(PermissionError):
    """The caller did not present a usable authenticated identity."""


class AuthenticationUnavailable(RuntimeError):
    """The requested authentication provider is not configured or available."""


class TenantAuthorizationError(PermissionError):
    """The authenticated principal is not a member of the selected tenant."""
