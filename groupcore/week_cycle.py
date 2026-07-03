from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class SavingWeek:
    cycle_start: date
    week_start: date
    week_number: int
    saving_year: int


def _first_matching_weekday_on_or_after(start_day, weekday):
    days_until_weekday = (weekday - start_day.weekday()) % 7
    return start_day + timedelta(days=days_until_weekday)


def current_saving_week(week_one_start, today=None):
    """
    Return the active saving week for the group.

    The configured week_one_start controls the original Week 1 and the weekday
    used for future cycles. After the first configured year, week numbering
    starts again in January, matching the group's yearly cash-out cycle.
    """
    today = today or date.today()

    if today.year <= week_one_start.year:
        cycle_start = week_one_start
    else:
        cycle_start = _first_matching_weekday_on_or_after(
            date(today.year, 1, 1),
            week_one_start.weekday(),
        )

    if today < cycle_start:
        return SavingWeek(
            cycle_start=cycle_start,
            week_start=cycle_start,
            week_number=1,
            saving_year=cycle_start.year,
        )

    weeks_since_start = ((today - cycle_start).days) // 7
    return SavingWeek(
        cycle_start=cycle_start,
        week_start=cycle_start + timedelta(weeks=weeks_since_start),
        week_number=weeks_since_start + 1,
        saving_year=cycle_start.year,
    )
