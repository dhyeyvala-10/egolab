"""
Cron expressions for pipeline schedules: five fields (minute hour day-of-month month day-of-week) with `*`,
lists, ranges, steps (`*/15`, `1-5/2`), month and weekday names, and the macros @hourly, @daily, @weekly,
@monthly, @yearly. As in Vixie cron, when both day fields are restricted a day matches either one.

Times are evaluated in the schedule's time zone. A time that doesn't exist that day (the hour skipped when
clocks go forward) is skipped; a time that happens twice (clocks going back) fires once, the first time.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MACROS = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *", "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@hourly": "0 * * * *",
}  # fmt: skip
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
DAYS = {d: i for i, d in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}
FIELDS = [("minute", 0, 59, {}), ("hour", 0, 23, {}), ("day of month", 1, 31, {}), ("month", 1, 12, MONTHS),
          ("day of week", 0, 7, DAYS)]  # fmt: skip
SEARCH_DAYS = 366 * 5


class CronError(ValueError):
    pass


def _value(token: str, lo: int, hi: int, names: dict[str, int], name: str) -> int:
    t = token.lower()
    if t in names:
        return names[t]
    if not t.isdigit():
        raise CronError(
            f"{name}: {token!r} isn't a number" + (f" or a name ({', '.join(names)})" if names else "")
        )
    v = int(t)
    if not lo <= v <= hi:
        raise CronError(f"{name}: {v} is outside {lo}–{hi}")
    return v


def _field(text: str, lo: int, hi: int, names: dict[str, int], name: str) -> tuple[frozenset[int], bool]:
    """(allowed values, restricted?) for one field."""
    out: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"{name}: empty list item")
        rng, _, step_s = part.partition("/")
        step = 1
        if step_s:
            if not step_s.isdigit() or int(step_s) == 0:
                raise CronError(f"{name}: step {step_s!r} must be a positive number")
            step = int(step_s)
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            x, _, y = rng.partition("-")
            a, b = _value(x, lo, hi, names, name), _value(y, lo, hi, names, name)
            if a > b:
                raise CronError(f"{name}: range {rng!r} runs backwards")
        else:
            a = _value(rng, lo, hi, names, name)
            b = hi if step_s else a
        out.update(range(a, b + 1, step))
    return frozenset(out), text != "*"


@dataclass(frozen=True)
class Cron:
    expr: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]  # 0 = Sunday
    days_restricted: bool
    weekdays_restricted: bool

    def matches_day(self, d: date) -> bool:
        if d.month not in self.months:
            return False
        dom, dow = d.day in self.days, (d.isoweekday() % 7) in self.weekdays
        if self.days_restricted and self.weekdays_restricted:
            return dom or dow
        return dom and dow


def parse(expr: str) -> Cron:
    text = " ".join(expr.strip().split())
    text = MACROS.get(text.lower(), text)
    parts = text.split(" ")
    if len(parts) != 5:
        raise CronError("A cron expression has five fields: minute hour day-of-month month day-of-week")
    parsed = [_field(p, lo, hi, names, name) for p, (name, lo, hi, names) in zip(parts, FIELDS, strict=True)]
    weekdays = frozenset(d % 7 for d in parsed[4][0])  # 7 is Sunday too
    return Cron(expr.strip(), parsed[0][0], parsed[1][0], parsed[2][0], parsed[3][0], weekdays,
                parsed[2][1], parsed[4][1])  # fmt: skip


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CronError(f"Unknown time zone {name!r}") from exc


def next_after(cron: Cron, after: datetime, tz: str = "UTC") -> datetime:
    """The first time strictly after `after` (aware) that the expression matches, as an aware UTC datetime."""
    z = zone(tz)
    local = after.astimezone(z)
    day = local.date()
    for _ in range(SEARCH_DAYS):
        if cron.matches_day(day):
            for h in sorted(cron.hours):
                for m in sorted(cron.minutes):
                    wall = datetime(day.year, day.month, day.day, h, m, tzinfo=z)  # fold=0: first occurrence
                    back = wall.astimezone(UTC).astimezone(z)
                    if (back.hour, back.minute) != (h, m):
                        continue  # doesn't exist today (clocks went forward)
                    at = wall.astimezone(UTC)
                    if at > after.astimezone(UTC):
                        return at
        day += timedelta(days=1)
    raise CronError(f"{cron.expr!r} never matches")


def upcoming(expr: str, tz: str, after: datetime, n: int = 5) -> list[datetime]:
    cron = parse(expr)
    out: list[datetime] = []
    t = after
    for _ in range(n):
        t = next_after(cron, t, tz)
        out.append(t)
    return out
