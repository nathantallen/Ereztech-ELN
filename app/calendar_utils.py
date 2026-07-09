import calendar as cal
from datetime import date, timedelta

from flask import request


def month_params():
    today = date.today()
    year = request.args.get("year", today.year, type=int)
    month = request.args.get("month", today.month, type=int)
    month = min(max(month, 1), 12)
    first = date(year, month, 1)
    last = date(year, month, cal.monthrange(year, month)[1])
    prev_month = first - timedelta(days=1)
    next_month = last + timedelta(days=1)
    return today, year, month, first, last, prev_month, next_month


def month_lane_grid(items, year, month, today, start_of, end_of):
    """Build a Mon-Sun month grid where each item keeps a stable lane per week,
    so multi-day bars line up across adjacent day cells."""
    first = date(year, month, 1)
    last = date(year, month, cal.monthrange(year, month)[1])
    grid_start = first - timedelta(days=first.weekday())
    grid_end = last + timedelta(days=6 - last.weekday())
    visible = [i for i in items if start_of(i) <= grid_end and end_of(i) >= grid_start]
    visible.sort(key=start_of)
    weeks, d = [], grid_start
    while d <= grid_end:
        week_start, week_end = d, d + timedelta(days=6)
        lanes = [i for i in visible if start_of(i) <= week_end and end_of(i) >= week_start]
        week = []
        for _ in range(7):
            week.append(
                {
                    "date": d,
                    "in_month": d.month == month,
                    "is_today": d == today,
                    "lanes": [i if start_of(i) <= d <= end_of(i) else None for i in lanes],
                }
            )
            d += timedelta(days=1)
        # Trim trailing empty lanes per day so cells don't reserve unused space.
        for day in week:
            while day["lanes"] and day["lanes"][-1] is None:
                day["lanes"].pop()
        weeks.append(week)
    return weeks, grid_start, grid_end
