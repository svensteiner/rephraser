"""Shared, side-effect-free result-state rules for user interfaces."""

from __future__ import annotations

from enum import StrEnum


class ResultState(StrEnum):
    READY = "ready"
    BUSY = "busy"
    CURRENT = "current"
    MANUALLY_EDITED = "manually_edited"
    STALE = "stale"


def classify_result_state(
    source: str,
    processed_source: str | None,
    generated_result: str,
    displayed_result: str,
    *,
    busy: bool = False,
) -> ResultState:
    if busy:
        return ResultState.BUSY
    if processed_source is None or not generated_result:
        return ResultState.READY
    if source != processed_source:
        return ResultState.STALE
    if displayed_result != generated_result:
        return ResultState.MANUALLY_EDITED
    return ResultState.CURRENT


def result_actions_allowed(state: ResultState) -> bool:
    return state in {ResultState.CURRENT, ResultState.MANUALLY_EDITED}
