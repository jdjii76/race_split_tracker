"""Post-race checkpoint invalidation orchestration."""
from __future__ import annotations

from split_tracker.auth import AppIdentity
from split_tracker.repository import RaceRepository, RepositoryError, SplitEvent


def remove_split_from_results(
    repository: RaceRepository,
    event: SplitEvent,
    reason: str,
    identity: AppIdentity | None,
    *,
    is_finish: bool = False,
) -> SplitEvent:
    """Append an audited void for a non-finish checkpoint split."""
    if identity is None or not identity.is_coach:
        raise RepositoryError("Only a coach or admin can remove a split from results.")
    if is_finish:
        raise RepositoryError("Finish results must be corrected through Manage Results.")
    reason = reason.strip()
    if not reason:
        raise RepositoryError("A correction reason is required.")
    return repository.remove_split_from_results(
        event.id,
        event.race_session_id,
        event.checkpoint_number,
        reason,
        identity.user_id,
        actor_role=identity.role,
    )
