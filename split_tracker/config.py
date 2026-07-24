"""Configuration loading helpers for optional Supabase integration."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Mapping, Literal

ConfigSource = Literal["streamlit_secrets", "environment", "missing", "mixed"]


@dataclass(frozen=True)
class SupabaseConfig:
    """Supabase configuration with secret values excluded from repr output."""

    url: str | None = field(default=None, repr=False)
    key: str | None = field(default=None, repr=False)
    source: ConfigSource = "missing"

    @property
    def is_configured(self) -> bool:
        """Return whether both required Supabase values are present."""
        return bool(self.url and self.key)

    @property
    def missing_fields(self) -> tuple[str, ...]:
        """Return the missing configuration field names without exposing values."""
        missing: list[str] = []
        if not self.url:
            missing.append("url")
        if not self.key:
            missing.append("key")
        return tuple(missing)

    def status(self) -> dict[str, object]:
        """Return a UI/log-safe status dictionary without secret values."""
        return {
            "configured": self.is_configured,
            "source": self.source,
            "missing_fields": self.missing_fields,
        }


def _strip(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping_get(mapping: object, key: str) -> object | None:
    if mapping is None:
        return None
    if isinstance(mapping, Mapping):
        return mapping.get(key)
    try:
        return mapping[key]  # type: ignore[index]
    except Exception:
        return None


def _current_streamlit_secrets() -> object | None:
    """Return Streamlit secrets when Streamlit is already imported."""
    streamlit = sys.modules.get("streamlit")
    if streamlit is None:
        return None
    return getattr(streamlit, "secrets", None)


def load_supabase_config(
    *,
    secrets: object | None = None,
    environ: Mapping[str, str] | None = None,
) -> SupabaseConfig:
    """Load Supabase URL and publishable key from Streamlit secrets, then env vars.

    Lookup order for each field:
    1. ``st.secrets["supabase"]["url"]`` / ``st.secrets["supabase"]["key"]``
    2. ``SUPABASE_URL`` / ``SUPABASE_KEY``

    Missing values are represented in the returned status and never raise by default.
    """
    env = os.environ if environ is None else environ
    active_secrets = _current_streamlit_secrets() if secrets is None else secrets
    supabase_secrets = _mapping_get(active_secrets, "supabase")

    secret_url = _strip(_mapping_get(supabase_secrets, "url"))
    secret_key = _strip(_mapping_get(supabase_secrets, "key"))
    env_url = _strip(env.get("SUPABASE_URL"))
    env_key = _strip(env.get("SUPABASE_KEY"))

    url = secret_url or env_url
    key = secret_key or env_key

    url_source = "streamlit_secrets" if secret_url else "environment" if env_url else "missing"
    key_source = "streamlit_secrets" if secret_key else "environment" if env_key else "missing"
    source: ConfigSource
    if url_source == key_source:
        source = url_source  # type: ignore[assignment]
    elif "missing" in {url_source, key_source}:
        source = "missing"
    else:
        source = "mixed"

    return SupabaseConfig(url=url, key=key, source=source)
