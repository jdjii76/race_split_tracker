"""Tests for optional Supabase configuration and client setup."""

from __future__ import annotations

from types import SimpleNamespace

from split_tracker.config import SupabaseConfig, load_supabase_config
from split_tracker.supabase_client import create_supabase_connection

SECRET_URL = "https://secret-project.supabase.com"
SECRET_KEY = "sb_publishable_secret_value"
ENV_URL = "https://env-project.supabase.com"
ENV_KEY = "sb_publishable_env_value"


def test_loads_supabase_configuration_from_environment(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    environ = {"SUPABASE_URL": ENV_URL, "SUPABASE_KEY": ENV_KEY}

    config = load_supabase_config(secrets={}, environ=environ)

    assert config.is_configured
    assert config.url == ENV_URL
    assert config.key == ENV_KEY
    assert config.source == "environment"
    assert config.missing_fields == ()


def test_missing_configuration_returns_status_without_crashing():
    config = load_supabase_config(secrets={}, environ={})

    assert not config.is_configured
    assert config.status() == {"configured": False, "source": "missing", "missing_fields": ("url", "key")}


def test_streamlit_secrets_are_preferred_over_environment(monkeypatch):
    fake_streamlit = SimpleNamespace(secrets={"supabase": {"url": SECRET_URL, "key": SECRET_KEY}})
    monkeypatch.setitem(__import__("sys").modules, "streamlit", fake_streamlit)
    environ = {"SUPABASE_URL": ENV_URL, "SUPABASE_KEY": ENV_KEY}

    config = load_supabase_config(environ=environ)

    assert config.is_configured
    assert config.url == SECRET_URL
    assert config.key == SECRET_KEY
    assert config.source == "streamlit_secrets"


def test_top_level_streamlit_secrets_are_supported_and_preferred(monkeypatch):
    fake_streamlit = SimpleNamespace(
        secrets={
            "SUPABASE_URL": SECRET_URL,
            "SUPABASE_KEY": SECRET_KEY,
            "supabase": {"url": "https://nested.supabase.com", "key": "nested-key"},
        }
    )
    monkeypatch.setitem(__import__("sys").modules, "streamlit", fake_streamlit)
    environ = {"SUPABASE_URL": ENV_URL, "SUPABASE_KEY": ENV_KEY}

    config = load_supabase_config(environ=environ)

    assert config.is_configured
    assert config.url == SECRET_URL
    assert config.key == SECRET_KEY
    assert config.source == "streamlit_secrets"


def test_secret_values_are_not_exposed_in_repr_status_or_missing_result():
    config = SupabaseConfig(url=SECRET_URL, key=SECRET_KEY, source="streamlit_secrets")
    missing_result = create_supabase_connection(SupabaseConfig(url=SECRET_URL, key=None, source="missing"))

    safe_text = f"{config!r} {config.status()} {missing_result!r} {missing_result.message}"

    assert SECRET_URL not in safe_text
    assert SECRET_KEY not in safe_text
    assert "publishable" not in missing_result.message.lower()


def test_client_is_created_only_when_both_values_are_present():
    calls: list[tuple[str, str]] = []

    def fake_factory(url: str, key: str) -> object:
        calls.append((url, key))
        return {"client": "created"}

    missing = create_supabase_connection(SupabaseConfig(url=ENV_URL, key=None, source="missing"), client_factory=fake_factory)
    configured = create_supabase_connection(SupabaseConfig(url=ENV_URL, key=ENV_KEY, source="environment"), client_factory=fake_factory)

    assert not missing.configured
    assert missing.client is None
    assert missing.missing_fields == ("key",)
    assert configured.configured
    assert configured.client == {"client": "created"}
    assert calls == [(ENV_URL, ENV_KEY)]
