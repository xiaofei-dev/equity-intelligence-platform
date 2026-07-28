from datetime import date, timedelta


class UnitedStatesMarketCalendar:
    """Deterministic NYSE/Nasdaq session calendar for refresh planning.

    Early closes are still trading sessions. Unexpected exchange closures must
    be supplied as explicit overrides by operations.
    """

    def __init__(self, closed_dates: frozenset[date] = frozenset()) -> None:
        self._closed_dates = closed_dates

    def is_session(self, value: date) -> bool:
        return value.weekday() < 5 and value not in self._holidays(value.year)

    def previous_session(self, value: date, inclusive: bool = False) -> date:
        candidate = value if inclusive else value - timedelta(days=1)
        while not self.is_session(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def shift_sessions(self, value: date, count: int) -> date:
        candidate = value
        direction = 1 if count >= 0 else -1
        remaining = abs(count)
        while remaining:
            candidate += timedelta(days=direction)
            if self.is_session(candidate):
                remaining -= 1
        return candidate

    def session_distance(self, older: date, newer: date) -> int:
        if older >= newer:
            return 0
        count = 0
        candidate = older
        while candidate < newer:
            candidate += timedelta(days=1)
            if self.is_session(candidate):
                count += 1
        return count

    def _holidays(self, year: int) -> frozenset[date]:
        fixed = {
            self._observed(date(year, 1, 1)),
            self._observed(date(year, 6, 19)),
            self._observed(date(year, 7, 4)),
            self._observed(date(year, 12, 25)),
            self._nth_weekday(year, 1, 0, 3),
            self._nth_weekday(year, 2, 0, 3),
            self._last_weekday(year, 5, 0),
            self._nth_weekday(year, 9, 0, 1),
            self._nth_weekday(year, 11, 3, 4),
            self._easter(year) - timedelta(days=2),
        }
        return frozenset(fixed | set(self._closed_dates))

    @staticmethod
    def _observed(value: date) -> date:
        if value.weekday() == 5:
            return value - timedelta(days=1)
        if value.weekday() == 6:
            return value + timedelta(days=1)
        return value

    @staticmethod
    def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
        value = date(year, month, 1)
        value += timedelta(days=(weekday - value.weekday()) % 7)
        return value + timedelta(weeks=occurrence - 1)

    @staticmethod
    def _last_weekday(year: int, month: int, weekday: int) -> date:
        value = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return value - timedelta(days=(value.weekday() - weekday) % 7)

    @staticmethod
    def _easter(year: int) -> date:
        a = year % 19
        b, c = divmod(year, 100)
        d, e = divmod(b, 4)
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i, k = divmod(c, 4)
        ell = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * ell) // 451
        month = (h + ell - 7 * m + 114) // 31
        day = (h + ell - 7 * m + 114) % 31 + 1
        return date(year, month, day)
