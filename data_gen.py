"""
data_gen.py
Simulates the analytics event pipeline landing table for PlaceMux.

This stands in for the real product database. It generates a realistic,
flawed event stream (nulls, duplicates, a stale feed, a spike anomaly,
a delayed outcome-data feed) on purpose, so the dashboard's data-quality
checks have something real to catch. This is NOT a happy-path dataset.

Event schema (one row = one landed analytics event):
    event_id        str   unique id (a few are duplicated on purpose)
    ts              datetime  when the event landed
    college_id      str
    student_id      str
    event_type      str   application_submitted | interview_scheduled |
                          interview_completed | offer_extended |
                          placement_confirmed
    company         str|None  (null on purpose for some rows)
    ctc_lpa         float|None  package offered, in LPA (null unless offer/placement)
    branch          str
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

RNG_SEED = 42
NOW = datetime(2026, 7, 4, 18, 0, 0)  # "today" for the demo, matches current date

COLLEGES = [
    {"id": "COL-DL01", "name": "Delhi Institute of Applied Sciences", "eligible": 420, "tier": "Tier 1"},
    {"id": "COL-PN02", "name": "Pune College of Engineering",         "eligible": 380, "tier": "Tier 1"},
    {"id": "COL-JP03", "name": "Jaipur School of Technology",         "eligible": 260, "tier": "Tier 2"},
    {"id": "COL-BH04", "name": "Bhopal Institute of Management & Tech","eligible": 190, "tier": "Tier 2"},
    {"id": "COL-KN05", "name": "Kanpur Rural Engineering College",    "eligible": 150, "tier": "Tier 3"},
]

BRANCHES = ["CSE", "ECE", "Mech", "Civil", "IT"]
COMPANIES = ["Tarna Systems", "Voltbase", "Northgate Retail", "Ferrolytics",
             "Quillhouse Media", "Sundeck Logistics", "Argento Fintech",
             "Brightloom Analytics", "Kelvin Manufacturing", "Paperlane HR Tech"]


def _gen_college_events(college, rng, is_stale=False, has_spike=False, outcome_delayed=False):
    """Generate the event funnel for one college across the last 60 days."""
    events = []
    eligible = college["eligible"]
    college_id = college["id"]

    # Funnel sizes: not everyone eligible applies, not everyone who applies gets an interview, etc.
    n_applications = int(eligible * rng.uniform(0.55, 0.8))
    n_interviews_scheduled = int(n_applications * rng.uniform(0.5, 0.7))
    n_interviews_completed = int(n_interviews_scheduled * rng.uniform(0.85, 0.97))
    n_offers = int(n_interviews_completed * rng.uniform(0.25, 0.45))
    n_placements = int(n_offers * rng.uniform(0.75, 0.95))  # some offers declined

    window_days = 55 if not is_stale else 55  # stale college simply stops emitting recently
    day_span_end = NOW - timedelta(days=4, hours=6) if is_stale else NOW

    def rand_ts(start_days_ago=window_days, end=day_span_end):
        start = end - timedelta(days=start_days_ago)
        delta = end - start
        return start + timedelta(seconds=int(rng.integers(0, int(delta.total_seconds()))))

    student_ids = [f"{college_id}-S{n:04d}" for n in range(1, eligible + 1)]

    def make_event(event_type, student_id, ts, company=None, ctc=None, missing_company=False):
        eid = f"{college_id}-{event_type[:3].upper()}-{len(events):06d}"
        events.append({
            "event_id": eid,
            "ts": ts,
            "college_id": college_id,
            "student_id": student_id,
            "event_type": event_type,
            "company": (None if missing_company else company),
            "ctc_lpa": ctc,
            "branch": rng.choice(BRANCHES),
        })
        return eid

    applicants = rng.choice(student_ids, size=n_applications, replace=False)
    for sid in applicants:
        ts = rand_ts()
        # ~1.5% of application rows land with a null company (form field bug) — intentional flaw
        make_event("application_submitted", sid, ts, missing_company=(rng.random() < 0.015))

    interviewed = rng.choice(applicants, size=min(n_interviews_scheduled, len(applicants)), replace=False)
    for sid in interviewed:
        ts = rand_ts()
        company = rng.choice(COMPANIES)
        make_event("interview_scheduled", sid, ts, company=company)

    completed = rng.choice(interviewed, size=min(n_interviews_completed, len(interviewed)), replace=False)
    for sid in completed:
        ts = rand_ts()
        company = rng.choice(COMPANIES)
        make_event("interview_completed", sid, ts, company=company)

    offered = rng.choice(completed, size=min(n_offers, len(completed)), replace=False)
    offer_ids = []
    for sid in offered:
        ts = rand_ts()
        company = rng.choice(COMPANIES)
        ctc = round(rng.uniform(3.2, 14.0), 1)
        eid = make_event("offer_extended", sid, ts, company=company, ctc=ctc)
        offer_ids.append((sid, ts, company, ctc))

    # Outcome data (placement_confirmed) depends on an upstream feed. If delayed,
    # we deliberately only land a fraction of confirmations, mirroring the real
    # "waiting on: Outcome data" dependency called out in the task brief.
    placements_source = offer_ids
    n_to_place = min(n_placements, len(placements_source))
    placed = rng.choice(len(placements_source), size=n_to_place, replace=False) if n_to_place > 0 else []
    if outcome_delayed:
        # Only ~35% of confirmed placements have actually landed so far this cycle
        placed = placed[: max(1, int(len(placed) * 0.35))]

    for idx in placed:
        sid, offer_ts, company, ctc = placements_source[idx]
        confirm_ts = offer_ts + timedelta(days=int(rng.integers(1, 10)))
        if confirm_ts > NOW:
            confirm_ts = NOW - timedelta(hours=int(rng.integers(1, 48)))
        make_event("placement_confirmed", sid, confirm_ts, company=company, ctc=ctc)

    if has_spike:
        # Inject an artificial one-day spike of duplicate-looking application events
        # (simulates a double-fire bug in the tracking snippet) for the sanity checker to catch.
        spike_day = NOW - timedelta(days=6)
        for _ in range(int(n_applications * 0.6)):
            sid = rng.choice(student_ids)
            ts = spike_day + timedelta(minutes=int(rng.integers(0, 1440)))
            make_event("application_submitted", sid, ts)

    return events


def generate_events(seed=RNG_SEED):
    rng = np.random.default_rng(seed)
    all_events = []

    for i, college in enumerate(COLLEGES):
        is_stale = (college["id"] == "COL-KN05")          # Kanpur feed has gone quiet
        has_spike = (college["id"] == "COL-JP03")          # Jaipur has a tracking double-fire bug
        outcome_delayed = (college["id"] == "COL-BH04")    # Bhopal's outcome-data feed is late
        all_events.extend(_gen_college_events(
            college, rng, is_stale=is_stale, has_spike=has_spike, outcome_delayed=outcome_delayed
        ))

    df = pd.DataFrame(all_events)
    df["ts"] = pd.to_datetime(df["ts"])

    # Inject duplicate rows for ONE college only (a landing-pipeline retry bug
    # on that college's webhook) — intentional flaw, isolated so the
    # duplicate-rate check demonstrably differentiates good feeds from bad ones.
    dl01_mask = df["college_id"] == "COL-DL01"
    dup_sample = df[dl01_mask].sample(frac=0.006, random_state=seed)
    df = pd.concat([df, dup_sample], ignore_index=True)

    df = df.sort_values("ts").reset_index(drop=True)
    return df


def college_lookup():
    return {c["id"]: c for c in COLLEGES}


if __name__ == "__main__":
    events = generate_events()
    events.to_csv("data/events.csv", index=False)
    print(f"Generated {len(events)} events across {events['college_id'].nunique()} colleges.")
    print(events.head())
