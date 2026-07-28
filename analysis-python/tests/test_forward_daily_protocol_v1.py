from equity_analysis.forward_validation.daily_protocol_v1 import (
    DAILY_ENROLLMENT_POLICY_VERSION,
    DAILY_PROTOCOL_VERSION,
)


def test_daily_protocol_versions_are_separate_from_weekly_v1() -> None:
    assert DAILY_PROTOCOL_VERSION == "FORWARD-VALIDATION-v1.1.0"
    assert DAILY_ENROLLMENT_POLICY_VERSION.startswith("DAILY-AFTER-CLOSE")
