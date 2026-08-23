"""Supabase Auth session and application-role helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AuthenticationError(RuntimeError):
    """A safe user-facing authentication or authorization failure."""


@dataclass(frozen=True)
class AppIdentity:
    user_id: str
    email: str
    role: str

    @property
    def is_coach(self) -> bool:
        return self.role in {"coach", "admin"}

    @property
    def is_timer(self) -> bool:
        return self.role == "timer"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _identity(client: Any, user: Any) -> AppIdentity:
    user_id = str(getattr(user, "id", "") or "")
    if not user_id:
        raise AuthenticationError("Your coach session has expired. Sign in again.")
    try:
        response = client.table("app_users").select("user_id,role").eq("user_id", user_id).limit(1).execute()
        rows = getattr(response, "data", None) or []
    except Exception as exc:
        raise AuthenticationError("Could not verify your KMHS application role.") from exc
    role = str(rows[0].get("role", "")) if rows else ""
    if role not in {"timer", "coach", "admin"}:
        raise AuthenticationError("This account is not authorized for the KMHS Running Split App.")
    return AppIdentity(user_id=user_id, email=str(getattr(user, "email", "") or ""), role=role)


def sign_in(client: Any, email: str, password: str) -> AppIdentity:
    """Sign in with Supabase Auth and verify the server-managed app role."""
    try:
        response = client.auth.sign_in_with_password({"email": email.strip(), "password": password})
        user = getattr(response, "user", None)
        identity = _identity(client, user)
    except AuthenticationError:
        try:
            client.auth.sign_out()
        except Exception:
            pass
        raise
    except Exception as exc:
        raise AuthenticationError("Sign in failed. Check your email and password.") from exc
    return identity


def current_identity(client: Any) -> AppIdentity | None:
    """Return the current valid identity; expired or missing sessions are anonymous."""
    try:
        session = client.auth.get_session()
        user = getattr(session, "user", None) if session else None
        return _identity(client, user) if user else None
    except AuthenticationError:
        return None
    except Exception:
        return None


def sign_out(client: Any) -> None:
    try:
        client.auth.sign_out()
    except Exception as exc:
        raise AuthenticationError("Could not sign out cleanly. Refresh before signing in again.") from exc


def require_coach(identity: AppIdentity | None) -> None:
    if identity is None or not identity.is_coach:
        raise AuthenticationError("Your coach session has expired. Sign in again.")


def require_admin(identity: AppIdentity | None) -> None:
    if identity is None or not identity.is_admin:
        raise AuthenticationError("Administrator access is required.")
