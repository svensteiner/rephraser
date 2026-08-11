from app.ui_state import ResultState, classify_result_state, result_actions_allowed


def test_result_state_transitions_are_explicit() -> None:
    assert classify_result_state("text", None, "", "") == ResultState.READY
    assert classify_result_state("text", "text", "result", "result", busy=True) == ResultState.BUSY
    assert classify_result_state("text", "text", "result", "result") == ResultState.CURRENT
    assert classify_result_state("text", "text", "result", "edited") == ResultState.MANUALLY_EDITED
    assert classify_result_state("changed", "text", "result", "result") == ResultState.STALE


def test_only_current_or_manually_edited_results_are_actionable() -> None:
    assert result_actions_allowed(ResultState.CURRENT)
    assert result_actions_allowed(ResultState.MANUALLY_EDITED)
    assert not result_actions_allowed(ResultState.STALE)
    assert not result_actions_allowed(ResultState.BUSY)
