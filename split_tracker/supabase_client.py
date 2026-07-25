"""Optional Supabase client construction utilities.

This module only prepares a client when configuration is available. It does not
query, insert, update, delete, or persist any application data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from split_tracker.config import SupabaseConfig, load_supabase_config

ClientFactory = Callable[[str, str], Any]


@dataclass(frozen=True)
class SupabaseConnectionResult:
    """Result object for Supabase client creation without exposing credentials."""

    configured: bool
    message: str
    missing_fields: tuple[str, ...] = ()
    client: Any | None = field(default=None, repr=False)


def create_supabase_connection(
    config: SupabaseConfig | None = None,
    *,
    client_factory: ClientFactory | None = None,
) -> SupabaseConnectionResult:
    """Create a Supabase client only when both URL and key are configured."""
    active_config = load_supabase_config() if config is None else config
    if not active_config.is_configured:
        return SupabaseConnectionResult(
            configured=False,
            message="Supabase configuration unavailable; set both URL and key.",
            missing_fields=active_config.missing_fields,
        )

    factory = client_factory
    if factory is None:
        from supabase import create_client

        factory = create_client

    client = factory(active_config.url or "", active_config.key or "")
    return SupabaseConnectionResult(
        configured=True,
        message="Supabase client configured.",
        client=client,
    )
