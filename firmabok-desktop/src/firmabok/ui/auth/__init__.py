"""Auth UI package (Phase 2): login, signup, recovery code, forgot password,
recovery-lost and first-run welcome screens + the AuthGate startup dialog.

All screens reuse ``core.accounts`` (Argon2id, single-use recovery codes,
rate limiting) and the existing design tokens/i18n layer. Nothing here
replaces the legacy app-lock (``ui.lock`` + ``core.auth``) — the two systems
coexist until the consolidation phase.
"""
from .common import (
    AuthScreenBase,
    LanguageToggle,
    PasswordField,
    PasswordStrengthMeter,
    password_strength,
)
from .forgot_password_screen import ForgotPasswordScreen
from .gate import AuthGate, accounts_exist
from .login_screen import LoginScreen
from .recovery_code_screen import RecoveryCodeScreen
from .recovery_lost_screen import RecoveryLostScreen
from .signup_screen import SignupScreen
from .welcome_screen import WelcomeScreen

__all__ = [
    "AuthGate", "AuthScreenBase", "ForgotPasswordScreen", "LanguageToggle",
    "LoginScreen", "PasswordField", "PasswordStrengthMeter",
    "RecoveryCodeScreen", "RecoveryLostScreen", "SignupScreen",
    "WelcomeScreen", "accounts_exist", "password_strength",
]
