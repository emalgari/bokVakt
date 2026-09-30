"""Domain exceptions carrying i18n message KEYS (never translated text).

The core layer is language-neutral: it raises errors with a stable key and
optional parameters; the UI layer translates at the boundary via
``i18n.tr(exc.key, **exc.params)``. DomainError subclasses ValueError so
generic ``except ValueError`` handlers keep working.
"""
from __future__ import annotations


class DomainError(ValueError):
    key = "error.generic"

    def __init__(self, key: str | None = None, **params):
        self.key = key or type(self).key
        self.params = params
        super().__init__(f"{self.key} {params if params else ''}".strip())


class OrgNrError(DomainError):
    pass


class VatNumberError(DomainError):
    pass


class InvoiceError(DomainError):
    pass


class BackupError(DomainError):
    pass


class ValidationError(DomainError):
    pass


class AuthError(DomainError):
    """Account/authentication errors (core.accounts). Carries auth.* keys."""
    pass
