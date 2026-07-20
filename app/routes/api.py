import csv
import io
from datetime import date, timedelta
from flask import Blueprint, jsonify, request, Response
from app.db import get_db

api_bp = Blueprint("api", __name__)


def _date_range(from_str, to_str):
    try:
        d0 = date.fromisoformat(from_str)
        d1 = date.fromisoformat(to_str)
    except Exception:
        d1 = date.today()
        d0 = d1 - timedelta(days=29)
    days = []
    cur = d0
    while cur <= d1:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _day_bounds(d):
    """Return (start_str, end_str) for a date as 'YYYY-MM-DD HH:MM:SS'."""
    return f"{d} 00:00:00", f"{d} 23:59:59"


def _sum_footfall(col, from_str, to_str):
    """Sum male+female visitors and group_count between two datetime strings (inclusive)."""
    pipeline = [
        {"$match": {"date_time": {"$gte": from_str, "$lte": to_str}}},
        {"$group": {
            "_id": None,
            "male":        {"$sum": "$count_male"},
            "female":      {"$sum": "$count_female"},
            "group_count": {"$sum": "$group_count"},
        }}
    ]
    res = list(col.aggregate(pipeline))
    if res:
        return (
            res[0]["male"] + res[0]["female"],
            res[0]["male"],
            res[0]["female"],
            res[0].get("group_count", 0),
        )
    return 0, 0, 0, 0


# ── Footfall endpoints ────────────────────────────────────────────────────────

@api_bp.route("/footfall/overview")
def footfall_overview():
    col = get_db()["footfall"]
    today = date.today()
    yesterday = today - timedelta(days=1)

    # week bounds
    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    last_week_end   = week_start - timedelta(days=1)

    # month bounds
    month_start = today.replace(day=1)
    last_month_end   = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    def day_total(d):
        s, e = _day_bounds(d)
        total, _, _, _ = _sum_footfall(col, s, e)
        return total

    def range_total(d0, d1):
        s = f"{d0} 00:00:00"
        e = f"{d1} 23:59:59"
        total, _, _, _ = _sum_footfall(col, s, e)
        return total

    # Selected date range breakdown
    from_str = request.args.get("from", str(today - timedelta(days=6)))
    to_str   = request.args.get("to",   str(today))
    s = f"{from_str} 00:00:00"
    e = f"{to_str} 23:59:59"

    # Restrict to the same 10:00-22:00 business-hours window shown in the hourly bar chart,
    # so the breakdown totals match what the bar chart displays.
    pipeline = [
        {"$match": {"date_time": {"$gte": s, "$lte": e}}},
        {"$addFields": {"hour": {"$substr": ["$date_time", 11, 2]}}},
        {"$match": {"hour": {"$gte": "10", "$lte": "22"}}},
        {"$group": {
            "_id": None,
            "male":        {"$sum": "$count_male"},
            "female":      {"$sum": "$count_female"},
            "group_count": {"$sum": "$group_count"},
        }}
    ]
    res = list(col.aggregate(pipeline))
    if res:
        male        = res[0]["male"]
        female      = res[0]["female"]
        group_count = res[0].get("group_count", 0)
    else:
        male = female = group_count = 0
    total = male + female

    periods = {
        "today":      day_total(today),
        "yesterday":  day_total(yesterday),
        "this_week":  range_total(week_start, today),
        "last_week":  range_total(last_week_start, last_week_end),
        "this_month": range_total(month_start, today),
        "last_month": range_total(last_month_start, last_month_end),
    }

    return jsonify({
        "periods": periods,
        "total_visitors": total,
        "breakdown": {"male": male, "female": female, "group_count": group_count},
    })


@api_bp.route("/footfall/trend")
def footfall_trend():
    col = get_db()["footfall"]
    from_str = request.args.get("from", "")
    to_str   = request.args.get("to", "")
    days = _date_range(from_str, to_str)

    labels   = [str(d) for d in days]
    visitors = []
    for d in days:
        s, e = _day_bounds(d)
        total, _, _, _ = _sum_footfall(col, s, e)
        visitors.append(total)

    s = f"{days[0]} 00:00:00" if days else ""
    e = f"{days[-1]} 23:59:59" if days else ""
    hours_pipeline = [
        {"$match": {"date_time": {"$gte": s, "$lte": e}}},
        {"$addFields": {"hour_bucket": {"$substr": ["$date_time", 0, 13]}}},
        {"$group": {"_id": "$hour_bucket"}},
        {"$count": "hours"},
    ]
    hours_res = list(col.aggregate(hours_pipeline)) if days else []
    hours_with_data = hours_res[0]["hours"] if hours_res else 0

    return jsonify({"labels": labels, "visitors": visitors, "hours_with_data": hours_with_data})


@api_bp.route("/footfall/hourly")
def footfall_hourly():
    col = get_db()["footfall"]
    from_str = request.args.get("from", str(date.today()))
    to_str   = request.args.get("to",   str(date.today()))
    s = f"{from_str} 00:00:00"
    e = f"{to_str} 23:59:59"

    pipeline = [
        {"$match": {"date_time": {"$gte": s, "$lte": e}}},
        {"$addFields": {"hour": {"$substr": ["$date_time", 11, 2]}}},
        {"$group": {
            "_id":         "$hour",
            "male":        {"$sum": "$count_male"},
            "female":      {"$sum": "$count_female"},
            "group_count": {"$sum": "$group_count"},
        }},
        {"$sort": {"_id": 1}}
    ]
    rows = {r["_id"]: r for r in col.aggregate(pipeline)}

    labels, values, male_vals, female_vals, group_vals = [], [], [], [], []
    for h in range(11, 24):
        key = f"{h:02d}"
        row = rows.get(key, {})
        m = row.get("male", 0)
        f = row.get("female", 0)
        g = row.get("group_count", 0)
        labels.append(f"{key}:00")
        values.append(m + f)
        male_vals.append(m)
        female_vals.append(f)
        group_vals.append(g)

    return jsonify({
        "labels": labels,
        "values": values,
        "male": male_vals,
        "female": female_vals,
        "group_count": group_vals,
    })


@api_bp.route("/footfall/hourly_csv")
def footfall_hourly_csv():
    col = get_db()["footfall"]
    from_str = request.args.get("from", str(date.today()))
    to_str   = request.args.get("to",   str(date.today()))
    days = _date_range(from_str, to_str)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Hour", "Male", "Female", "Total", "Group Count"])

    for d in days:
        s, e = _day_bounds(d)
        pipeline = [
            {"$match": {"date_time": {"$gte": s, "$lte": e}}},
            {"$addFields": {"hour": {"$substr": ["$date_time", 11, 2]}}},
            {"$group": {
                "_id":         "$hour",
                "male":        {"$sum": "$count_male"},
                "female":      {"$sum": "$count_female"},
                "group_count": {"$sum": "$group_count"},
            }},
            {"$sort": {"_id": 1}}
        ]
        rows = {r["_id"]: r for r in col.aggregate(pipeline)}
        for h in range(11, 24):
            key = f"{h:02d}"
            row = rows.get(key, {})
            m = row.get("male", 0)
            f = row.get("female", 0)
            g = row.get("group_count", 0)
            writer.writerow([str(d), f"{key}:00", m, f, m + f, g])

    output.seek(0)
    filename = f"footfall_{from_str}_to_{to_str}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@api_bp.route("/footfall/breakdown")
def footfall_breakdown():
    col = get_db()["footfall"]
    from_str = request.args.get("from", str(date.today()))
    to_str   = request.args.get("to",   str(date.today()))
    s = f"{from_str} 00:00:00"
    e = f"{to_str} 23:59:59"
    _, male, female, group_count = _sum_footfall(col, s, e)
    return jsonify({"male": male, "female": female, "group_count": group_count})
