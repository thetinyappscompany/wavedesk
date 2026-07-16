"""Anti-ban intelligence (Phase 3 feature 6 — the differentiator).

Keeps WhatsApp numbers healthy under bulk load:
  - number warm-up: a per-number daily send cap that ramps from day-1 (20 msgs)
    to day-30 (the number's full target), enforced by the broadcast driver;
  - health score (0-100) from the recent delivery-failure rate + connection
    status, with a derived ban-risk level surfaced in the UI;
  - humanized pacing (variable delays) already lives in the broadcast driver;
    typing-presence-before-send is a gateway capability (deferred).

Warm-up dates are plain dates; caps are per calendar day (server date).
"""

import frappe
from frappe.query_builder.functions import Count
from frappe.utils import add_to_date, getdate, now_datetime, today


def _outbound_via_number(number_name: str, since):
    """Base query: outbound messages dispatched through this number since `since`."""
    m = frappe.qb.DocType("WD Message")
    c = frappe.qb.DocType("WD Chat")
    return (
        frappe.qb.from_(m)
        .join(c)
        .on(m.chat == c.name)
        .where((c.number == number_name) & (m.direction == "out") & (m.creation >= since))
    )

WARMUP_DAY1_CAP = 20
WARMUP_DAYS = 30
WARMUP_CEILING = 1000  # ramp target when a number has no explicit daily limit
HEALTH_WINDOW_DAYS = 7
FAILURE_WEIGHT = 60  # a 100%-failure window costs this many health points


# ---------------------------------------------------------------------------
# Warm-up caps
# ---------------------------------------------------------------------------

def warmup_cap(started_on, target: int, on_date) -> int | None:
    """Today's send cap for a number. None = unlimited (not warming, no target)."""
    full = target or 0
    if not started_on:
        return full or None  # not warming → the full target (unlimited if 0)
    day = (getdate(on_date) - getdate(started_on)).days + 1
    if day < 1:
        day = 1
    ceiling = full or WARMUP_CEILING
    if day >= WARMUP_DAYS:
        return full or None  # warmed → target (unlimited if 0)
    ramped = round(WARMUP_DAY1_CAP + (ceiling - WARMUP_DAY1_CAP) * (day - 1) / (WARMUP_DAYS - 1))
    return max(WARMUP_DAY1_CAP, min(ramped, ceiling))


def warmup_day(number_doc, on_date=None) -> int:
    if not number_doc.warmup_started_on:
        return 0
    day = (getdate(on_date or today()) - getdate(number_doc.warmup_started_on)).days + 1
    return max(1, day)


def daily_cap_for(number_doc, on_date=None) -> int | None:
    return warmup_cap(number_doc.warmup_started_on, int(number_doc.daily_send_limit or 0),
                      on_date or today())


def sent_today(number_name: str) -> int:
    """Outbound messages dispatched via this number since local midnight."""
    start = getdate(today())
    return _outbound_via_number(number_name, start).select(Count("*")).run()[0][0]


def can_dispatch(number_name: str) -> bool:
    """Whether the number is under its warm-up cap for today."""
    num = frappe.db.get_value(
        "WD WhatsApp Number", number_name, ["warmup_started_on", "daily_send_limit"], as_dict=True
    )
    if not num:
        return True
    cap = warmup_cap(num.warmup_started_on, int(num.daily_send_limit or 0), today())
    if cap is None:
        return True
    return sent_today(number_name) < cap


# ---------------------------------------------------------------------------
# Health score
# ---------------------------------------------------------------------------

def compute_health(number_name: str) -> dict:
    """Score a number 0-100 from its recent failure rate + connection status,
    store it, and return {score, risk}."""
    num = frappe.db.get_value(
        "WD WhatsApp Number", number_name, ["status"], as_dict=True
    )
    if not num:
        return {"score": 0, "risk": "high"}
    window = add_to_date(now_datetime(), days=-HEALTH_WINDOW_DAYS)
    m = frappe.qb.DocType("WD Message")
    rows = (
        _outbound_via_number(number_name, window)
        .select(m.status.as_("status"), Count("*").as_("n"))
        .groupby(m.status)
    ).run(as_dict=True)
    dispatched = sum(r.n for r in rows)
    failed = sum(r.n for r in rows if r.status == "failed")
    failure_rate = (failed / dispatched) if dispatched else 0.0

    score = 100 - round(failure_rate * FAILURE_WEIGHT)
    if num.status == "banned":
        score = 0
    elif num.status == "disconnected":
        score -= 20
    score = max(0, min(100, score))
    risk = _risk_from(score, failure_rate, num.status)

    frappe.db.set_value(
        "WD WhatsApp Number",
        number_name,
        {"health_score": score, "risk_level": risk, "health_checked_at": now_datetime()},
        update_modified=False,
    )
    return {"score": score, "risk": risk, "failure_rate": failure_rate, "dispatched": dispatched}


def _risk_from(score: int, failure_rate: float, status: str) -> str:
    if status == "banned" or score < 40 or failure_rate > 0.25:
        return "high"
    if score < 70 or failure_rate > 0.1 or status == "disconnected":
        return "medium"
    return "low"


def recompute_all_health() -> int:
    """Nightly cron: refresh every number's health score + warm-up stage."""
    numbers = frappe.get_all(
        "WD WhatsApp Number", fields=["name", "warmup_started_on"], ignore_permissions=True
    )
    for row in numbers:
        compute_health(row.name)
        if row.warmup_started_on:
            frappe.db.set_value(
                "WD WhatsApp Number",
                row.name,
                "warmup_stage",
                warmup_day(frappe._dict(warmup_started_on=row.warmup_started_on)),
                update_modified=False,
            )
    return len(numbers)
