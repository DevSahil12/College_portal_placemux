"""
metrics.py
Event -> Metric -> Decision layer.

Every function here is the single source of truth for one number on the
dashboard. The dashboard UI never computes a metric inline — it always
calls one of these, so "where does this number come from" always has a
one-line answer: "metrics.py::<function_name>".
"""
import numpy as np
import pandas as pd
from datetime import timedelta

FRESHNESS_SLA_HOURS = 24
NULL_RATE_WARN = 0.01     # 1%
NULL_RATE_FAIL = 0.03     # 3%
DUP_RATE_FAIL = 0.001     # 0.1%
SPIKE_Z_THRESHOLD = 3.0


class TenantAccessError(PermissionError):
    """Raised when a query tries to read a college's data without matching
    tenant scope. Every read path in this module goes through
    scope_events(), so this is not optional per-caller enforcement — it's
    enforced once, centrally."""
    pass


def scope_events(events: pd.DataFrame, requester_college_id: str, target_college_id: str) -> pd.DataFrame:
    """
    The ONLY function allowed to slice the events table by college.
    A logged-in placement officer's requester_college_id must match the
    target_college_id they're asking about, or the read is rejected.
    This is what makes "can one college see another's data" provably no.
    """
    if requester_college_id != target_college_id:
        raise TenantAccessError(
            f"college {requester_college_id} is not authorized to read data for {target_college_id}"
        )
    return events[events["college_id"] == target_college_id].copy()


def funnel_counts(scoped: pd.DataFrame) -> dict:
    """Counts of distinct students at each funnel stage. Source: event log,
    event_type column. Decision: which stage is leaking students."""
    out = {}
    for stage in ["application_submitted", "interview_scheduled",
                  "interview_completed", "offer_extended", "placement_confirmed"]:
        out[stage] = scoped.loc[scoped["event_type"] == stage, "student_id"].nunique()
    return out


def placement_rate(scoped: pd.DataFrame, eligible: int, outcome_delayed: bool) -> dict:
    """Placements confirmed / eligible students.
    Source: placement_confirmed events / roster.eligible_count.
    Decision: if trending low with time running out, escalate to the
    outreach team to book more company drives this week."""
    placed = scoped.loc[scoped["event_type"] == "placement_confirmed", "student_id"].nunique()
    rate = placed / eligible if eligible else 0.0
    return {
        "placed": placed,
        "eligible": eligible,
        "rate": rate,
        "confidence": "partial — outcome data feed delayed" if outcome_delayed else "complete",
    }


def conversion_rate(scoped: pd.DataFrame, from_stage: str, to_stage: str) -> float:
    """Stage-to-stage conversion. Source: event log.
    Decision: a low interview->offer rate says run mock-interview prep;
    a low scheduled->completed rate says students are ghosting slots."""
    frm = scoped.loc[scoped["event_type"] == from_stage, "student_id"].nunique()
    to = scoped.loc[scoped["event_type"] == to_stage, "student_id"].nunique()
    return (to / frm) if frm else 0.0


def average_ctc(scoped: pd.DataFrame) -> float:
    """Mean CTC (LPA) across confirmed placements. Source: placement_confirmed.ctc_lpa.
    Decision: below-market average CTC for a college/branch says the college
    needs stronger companies in its pipeline, not just more of them."""
    vals = scoped.loc[scoped["event_type"] == "placement_confirmed", "ctc_lpa"].dropna()
    return float(vals.mean()) if len(vals) else 0.0


def freshness_check(scoped: pd.DataFrame, now) -> dict:
    """How old is the newest landed event for this college.
    Source: max(events.ts). Decision: past SLA -> stop trusting every
    number on this college's tab and page the data-eng on-call."""
    if scoped.empty:
        return {"last_event": None, "age_hours": None, "status": "NO DATA"}
    last = scoped["ts"].max()
    age_hours = (now - last).total_seconds() / 3600
    status = "PASS" if age_hours <= FRESHNESS_SLA_HOURS else "FAIL"
    return {"last_event": last, "age_hours": age_hours, "status": status}


def null_rate_check(scoped: pd.DataFrame) -> dict:
    """Share of rows missing a required field for their event type
    (company on scheduled/completed/offer/placement events).
    Source: null count / row count. Decision: FAIL blocks the number
    from being shown as 'complete' — flag to data-eng, don't silently
    average over the gap."""
    required_company = scoped[scoped["event_type"].isin(
        ["interview_scheduled", "interview_completed", "offer_extended", "placement_confirmed"]
    )]
    if required_company.empty:
        return {"rate": 0.0, "status": "PASS", "missing": 0, "total": 0}
    missing = required_company["company"].isna().sum()
    total = len(required_company)
    rate = missing / total
    status = "FAIL" if rate >= NULL_RATE_FAIL else ("WARN" if rate >= NULL_RATE_WARN else "PASS")
    return {"rate": rate, "status": status, "missing": int(missing), "total": int(total)}


def duplicate_rate_check(scoped: pd.DataFrame) -> dict:
    """Share of event_ids that appear more than once (landing-pipeline
    retry bug). Source: duplicated event_id count / row count.
    Decision: FAIL means de-dupe before this feeds any external report."""
    total = len(scoped)
    if total == 0:
        return {"rate": 0.0, "status": "PASS", "duplicates": 0, "total": 0}
    dup_count = int(scoped["event_id"].duplicated().sum())
    rate = dup_count / total
    status = "FAIL" if rate > DUP_RATE_FAIL else "PASS"
    return {"rate": rate, "status": status, "duplicates": dup_count, "total": total}


def spike_check(scoped: pd.DataFrame, event_type: str = "application_submitted") -> dict:
    """Z-score anomaly check on daily counts of one event type.
    Source: daily event counts, std dev over the trailing window.
    Decision: a flagged day should be excluded from trend reporting
    until confirmed real, and investigated as a possible double-fire bug."""
    daily = (scoped[scoped["event_type"] == event_type]
             .assign(day=lambda d: d["ts"].dt.date)
             .groupby("day").size())
    if len(daily) < 5:
        return {"status": "PASS", "flagged_days": [], "series": daily}
    mean, std = daily.mean(), daily.std()
    if std == 0 or np.isnan(std):
        return {"status": "PASS", "flagged_days": [], "series": daily}
    z = (daily - mean) / std
    flagged = daily[z.abs() >= SPIKE_Z_THRESHOLD]
    status = "FLAG" if len(flagged) else "PASS"
    return {"status": status, "flagged_days": list(flagged.items()), "series": daily}


def daily_trend(scoped: pd.DataFrame, event_type: str) -> pd.Series:
    daily = (scoped[scoped["event_type"] == event_type]
             .assign(day=lambda d: d["ts"].dt.date)
             .groupby("day").size())
    return daily
