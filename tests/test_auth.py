"""Application identity and role separation tests."""
import pytest

from split_tracker.auth import AuthenticationError, AppIdentity, current_identity, require_admin, require_coach, sign_in


class Result:
    def __init__(self, data=None, user=None): self.data, self.user = data, user


class User:
    id = "user-1"
    email = "coach@example.com"


class Query:
    def __init__(self, role): self.role = role
    def select(self, *_): return self
    def eq(self, *_): return self
    def limit(self, *_): return self
    def execute(self): return Result([{"user_id": "user-1", "role": self.role}] if self.role else [])


class Auth:
    def __init__(self): self.signed_out = False
    def sign_in_with_password(self, credentials):
        assert credentials == {"email": "coach@example.com", "password": "secret"}
        return Result(user=User())
    def get_session(self): return Result(user=User())
    def sign_out(self): self.signed_out = True


class Client:
    def __init__(self, role): self.role, self.auth = role, Auth()
    def table(self, name): assert name == "app_users"; return Query(self.role)


def test_sign_in_uses_supabase_auth_and_server_role():
    identity = sign_in(Client("coach"), "coach@example.com", "secret")
    assert identity.email == "coach@example.com" and identity.is_coach and not identity.is_admin


def test_unprovisioned_authenticated_user_is_rejected_and_signed_out():
    client = Client("")
    with pytest.raises(AuthenticationError, match="not authorized"):
        sign_in(client, "coach@example.com", "secret")
    assert client.auth.signed_out


def test_role_helpers_separate_coach_and_admin():
    coach = AppIdentity("c", "c@example.com", "coach")
    admin = AppIdentity("a", "a@example.com", "admin")
    require_coach(coach)
    require_coach(admin)
    require_admin(admin)
    with pytest.raises(AuthenticationError, match="Administrator"):
        require_admin(coach)
    with pytest.raises(AuthenticationError, match="expired"):
        require_coach(None)


def test_current_identity_survives_rerun_client_session():
    assert current_identity(Client("admin")).is_admin


def test_timer_identity_is_authorized_without_coach_access():
    identity = current_identity(Client("timer"))
    assert identity is not None
    assert identity.is_timer
    assert not identity.is_coach
