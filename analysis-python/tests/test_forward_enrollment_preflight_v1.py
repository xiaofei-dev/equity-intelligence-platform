from datetime import date

from equity_analysis.forward_validation.enrollment_preflight_v1 import (
    is_regular_weekday_session_candidate,
)


def test_july_31_2026_is_a_regular_weekday_candidate() -> None:
    assert is_regular_weekday_session_candidate(date(2026, 7, 31))


def test_independence_day_observed_is_not_a_session() -> None:
    assert not is_regular_weekday_session_candidate(date(2026, 7, 3))


def test_weekend_is_not_a_session() -> None:
    assert not is_regular_weekday_session_candidate(date(2026, 8, 1))
