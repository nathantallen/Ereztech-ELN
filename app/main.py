import calendar as cal

from flask import Blueprint, redirect, render_template, url_for
from flask_login import login_required

from .calendar_utils import month_lane_grid, month_params
from .models import ProductionRun, Reactor

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    return redirect(url_for("main.month_calendar"))


@bp.route("/calendar")
@login_required
def month_calendar():
    today, year, month, first, last, prev_m, next_m = month_params()
    runs = ProductionRun.query.order_by(ProductionRun.start_date).all()
    weeks, _, _ = month_lane_grid(
        runs, year, month, today, lambda r: r.start_date, lambda r: r.end_date
    )
    return render_template(
        "calendar.html",
        weeks=weeks,
        year=year,
        month=month,
        month_name=cal.month_name[month],
        prev_m=prev_m,
        next_m=next_m,
    )


@bp.route("/timeline")
@login_required
def timeline():
    today, year, month, first, last, prev_m, next_m = month_params()
    days = last.day
    reactors = Reactor.query.order_by(Reactor.name).all()
    runs = (
        ProductionRun.query.filter(
            ProductionRun.start_date <= last, ProductionRun.end_date >= first
        )
        .order_by(ProductionRun.start_date)
        .all()
    )
    rows = []
    for reactor in reactors:
        bars = []
        for r in runs:
            if r.reactor_id != reactor.id:
                continue
            start_col = max(r.start_date, first).day
            end_col = min(r.end_date, last).day
            bars.append(
                {
                    "run": r,
                    "col_start": start_col,
                    "col_end": end_col + 1,
                    "clipped_left": r.start_date < first,
                    "clipped_right": r.end_date > last,
                }
            )
        rows.append({"reactor": reactor, "bars": bars})
    today_col = today.day if (today.year == year and today.month == month) else None
    return render_template(
        "timeline.html",
        rows=rows,
        days=days,
        year=year,
        month=month,
        month_name=cal.month_name[month],
        prev_m=prev_m,
        next_m=next_m,
        today_col=today_col,
    )
