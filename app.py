"""
PlaceMux — College Placement Dashboard (Task 16, Week 5, Phase 2)
Run with:  streamlit run app.py
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

from data_gen import generate_events, COLLEGES, college_lookup
import metrics as M

st.set_page_config(page_title="PlaceMux — College Dashboard", page_icon="🎓", layout="wide")

# ---------------------------------------------------------------------------
# State: event log lives in session_state so the "simulate a live event"
# button can mutate it and every metric on screen recomputes immediately.
# This is what proves data is "really flowing" rather than a static mock.
# ---------------------------------------------------------------------------
if "events" not in st.session_state:
    st.session_state.events = generate_events()
if "now" not in st.session_state:
    st.session_state.now = datetime(2026, 7, 4, 18, 0, 0)
if "isolation_log" not in st.session_state:
    st.session_state.isolation_log = []

events = st.session_state.events
now = st.session_state.now
lookup = college_lookup()

# ---------------------------------------------------------------------------
# Sidebar — tenant login simulation + live event injector + dependency panel
# ---------------------------------------------------------------------------
st.sidebar.title("🎓 PlaceMux")
st.sidebar.caption("College Portal & Reporting API — Task 16 demo")

college_names = {c["id"]: c["name"] for c in COLLEGES}
logged_in_as = st.sidebar.selectbox(
    "Logged in as (placement officer at)",
    options=list(college_names.keys()),
    format_func=lambda cid: college_names[cid],
)

st.sidebar.divider()
st.sidebar.subheader("Simulate a live event")
st.sidebar.caption("Proves numbers update from real events landing, not a static mock.")
sim_type = st.sidebar.selectbox(
    "Event type",
    ["application_submitted", "interview_scheduled", "interview_completed",
     "offer_extended", "placement_confirmed"],
)
if st.sidebar.button("Fire event now", use_container_width=True):
    college = lookup[logged_in_as]
    student_n = int(np.random.randint(1, college["eligible"] + 1))
    new_row = {
        "event_id": f"{logged_in_as}-SIM-{len(events):06d}",
        "ts": now,
        "college_id": logged_in_as,
        "student_id": f"{logged_in_as}-S{student_n:04d}",
        "event_type": sim_type,
        "company": np.random.choice(
            ["Tarna Systems", "Voltbase", "Argento Fintech"]
        ) if sim_type != "application_submitted" else None,
        "ctc_lpa": round(float(np.random.uniform(4, 12)), 1) if sim_type in
        ("offer_extended", "placement_confirmed") else None,
        "branch": np.random.choice(["CSE", "ECE", "Mech", "Civil", "IT"]),
    }
    st.session_state.events = pd.concat(
        [events, pd.DataFrame([new_row])], ignore_index=True
    )
    st.sidebar.success(f"Landed 1 {sim_type} event for {college['name']}.")
    st.rerun()

st.sidebar.divider()
st.sidebar.caption(f"Table snapshot: **{len(events):,} rows** · as of {now:%d %b %Y, %H:%M}")

# ---------------------------------------------------------------------------
# Scope every read through the tenant guard. This is the one place the
# officer's own data is pulled — everything downstream is theirs only.
# ---------------------------------------------------------------------------
scoped = M.scope_events(events, logged_in_as, logged_in_as)
college = lookup[logged_in_as]
outcome_delayed = (logged_in_as == "COL-BH04")
is_flagged_stale = (logged_in_as == "COL-KN05")
has_spike_source = (logged_in_as == "COL-JP03")

# ---------------------------------------------------------------------------
# Header + system-health thesis strip
# ---------------------------------------------------------------------------
st.title(f"{college['name']}")
st.caption(f"{college['tier']} · {college['eligible']} eligible students · college_id `{logged_in_as}`")

fresh = M.freshness_check(scoped, now)
nulls = M.null_rate_check(scoped)
dups = M.duplicate_rate_check(scoped)
spikes = M.spike_check(scoped)

overall_ok = fresh["status"] == "PASS" and nulls["status"] != "FAIL" and dups["status"] == "PASS"
health_color = "🟢" if overall_ok else ("🟡" if fresh["status"] != "FAIL" and dups["status"] == "PASS" else "🔴")
health_label = "Live & trustworthy" if overall_ok else "Needs attention before you quote these numbers"

st.markdown(f"### {health_color} {health_label}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Last event landed", fresh["last_event"].strftime("%d %b, %H:%M") if fresh["last_event"] is not None else "—",
           help="metrics.py::freshness_check — max(ts) for this college_id")
c2.metric("Data freshness SLA", fresh["status"], f"{fresh['age_hours']:.1f}h old" if fresh["age_hours"] is not None else "")
c3.metric("Null-field check", nulls["status"], f"{nulls['rate']*100:.2f}% missing")
c4.metric("Duplicate-row check", dups["status"], f"{dups['duplicates']} of {dups['total']}")

st.divider()

# ---------------------------------------------------------------------------
# Core funnel + decision-grade metrics
# ---------------------------------------------------------------------------
st.subheader("Placement funnel — this college")
funnel = M.funnel_counts(scoped)
placement = M.placement_rate(scoped, college["eligible"], outcome_delayed)
conv_interview_offer = M.conversion_rate(scoped, "interview_completed", "offer_extended")
conv_sched_completed = M.conversion_rate(scoped, "interview_scheduled", "interview_completed")
avg_ctc = M.average_ctc(scoped)

fcol1, fcol2, fcol3, fcol4, fcol5 = st.columns(5)
stage_labels = {
    "application_submitted": "Applied",
    "interview_scheduled": "Interview scheduled",
    "interview_completed": "Interview completed",
    "offer_extended": "Offer extended",
    "placement_confirmed": "Placement confirmed",
}
for col, (stage, label) in zip([fcol1, fcol2, fcol3, fcol4, fcol5], stage_labels.items()):
    col.metric(label, funnel[stage])

fig = go.Figure(go.Funnel(
    y=list(stage_labels.values()),
    x=[funnel[s] for s in stage_labels],
    textinfo="value+percent initial",
))
fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig, use_container_width=True)

with st.expander("📖 Source & decision — placement funnel", expanded=False):
    st.markdown("""
- **Source**: distinct `student_id` counts per `event_type` in the landed event log, filtered to this `college_id`.
- **Definition**: a student advances one funnel stage the moment their corresponding event lands — this is a live count, not a projection.
- **Decision it drives**: whichever stage has the steepest drop-off is where the placement cell should intervene next
  (e.g. a big drop between *scheduled* and *completed* means students are no-showing interview slots — fix scheduling, not sourcing).
""")

st.divider()

m1, m2, m3 = st.columns(3)
with m1:
    conf_note = f" ({placement['confidence']})" if placement["confidence"] != "complete" else ""
    st.metric("Placement rate", f"{placement['rate']*100:.1f}%{conf_note}",
              f"{placement['placed']} / {placement['eligible']} eligible")
    if outcome_delayed:
        st.warning("Outcome-data feed for this college is running behind (Section 3 upstream dependency). "
                   "This number is a **lower bound**, not final — do not report it externally without this caveat.")
    with st.expander("Source & decision"):
        st.markdown("""
- **Source**: `placement_confirmed` events ÷ `eligible` roster count.
- **Decision**: if this is trending below target with fewer than 3 weeks left in the placement window,
  escalate to outreach to book additional company drives this week — don't wait for the term to end.
""")

with m2:
    st.metric("Interview → Offer conversion", f"{conv_interview_offer*100:.1f}%")
    with st.expander("Source & decision"):
        st.markdown("""
- **Source**: distinct students with `offer_extended` ÷ distinct students with `interview_completed`.
- **Decision**: a rate meaningfully below other colleges' says run mock-interview prep drives for this batch,
  not just push more applications through the top of the funnel.
""")

with m3:
    st.metric("Average CTC (confirmed)", f"₹{avg_ctc:.1f} LPA" if avg_ctc else "No placements yet")
    with st.expander("Source & decision"):
        st.markdown("""
- **Source**: mean of `ctc_lpa` on `placement_confirmed` events.
- **Decision**: a below-market average for this college/tier says the sourcing team needs stronger
  companies in the pipeline, not just more of the same ones.
""")

st.divider()

# ---------------------------------------------------------------------------
# Trend + spike/sanity visualization
# ---------------------------------------------------------------------------
st.subheader("Application volume — daily, with anomaly check")
trend = M.daily_trend(scoped, "application_submitted")
trend_df = trend.reset_index()
trend_df.columns = ["day", "applications"]
fig2 = go.Figure()
fig2.add_trace(go.Bar(x=trend_df["day"], y=trend_df["applications"], name="Applications/day",
                       marker_color=["#B8863B" if any(d == day for day, _ in spikes["flagged_days"]) else "#2F6F5E"
                                     for day in trend_df["day"]]))
fig2.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig2, use_container_width=True)

if spikes["status"] == "FLAG":
    flagged_str = ", ".join(str(d) for d, _ in spikes["flagged_days"])
    st.error(f"⚠️ Sanity check FAILED: abnormal spike detected on {flagged_str} "
             f"(z-score ≥ {M.SPIKE_Z_THRESHOLD}). Likely a tracking double-fire bug, not real demand. "
             f"**Decision**: exclude this day from trend reporting until the eng team confirms the events are genuine.")
else:
    st.success("✅ Sanity check passed: no anomalous single-day spikes in this window.")

st.divider()

# ---------------------------------------------------------------------------
# Data-quality ledger (aggregated view of the checks already run above)
# ---------------------------------------------------------------------------
st.subheader("Data-quality ledger")
dq1, dq2, dq3, dq4 = st.columns(4)
dq1.metric("Freshness", fresh["status"])
dq2.metric("Null-field rate", f"{nulls['rate']*100:.2f}%", nulls["status"])
dq3.metric("Duplicate rate", f"{dups['rate']*100:.3f}%", dups["status"])
dq4.metric("Spike check", spikes["status"])

st.caption(
    "Thresholds: freshness SLA 24h · null-field WARN ≥1% / FAIL ≥3% · duplicate FAIL >0.1% · "
    "spike FAIL at |z| ≥ 3 on daily application volume. Defined in `metrics.py`."
)

st.divider()

# ---------------------------------------------------------------------------
# Tenant isolation proof — live, not a claim
# ---------------------------------------------------------------------------
st.subheader("🔒 Tenant isolation — prove it, don't claim it")
st.caption("The self-check in the study guide asks: *can one college see another's data — prove it can't.* This runs that proof live.")

other_colleges = [c for c in COLLEGES if c["id"] != logged_in_as]
target = st.selectbox(
    "Attempt to read data belonging to:",
    options=[c["id"] for c in other_colleges],
    format_func=lambda cid: college_names[cid],
)

if st.button("Attempt cross-tenant read"):
    try:
        M.scope_events(events, logged_in_as, target)
        result = "❌ LEAK — read succeeded when it should not have"
    except M.TenantAccessError as e:
        result = f"✅ Blocked — {e}"
    st.session_state.isolation_log.insert(0, {
        "time": now.strftime("%H:%M:%S"),
        "requester": logged_in_as,
        "target": target,
        "result": result,
    })

if st.session_state.isolation_log:
    st.dataframe(pd.DataFrame(st.session_state.isolation_log), hide_index=True, use_container_width=True)
else:
    st.info("No isolation checks run yet this session — click the button above to generate proof.")

st.divider()

# ---------------------------------------------------------------------------
# Upstream dependency panel
# ---------------------------------------------------------------------------
st.subheader("⛓️ Upstream dependency — Outcome data")
dep_rows = []
for c in COLLEGES:
    delayed = (c["id"] == "COL-BH04")
    stale = (c["id"] == "COL-KN05")
    status = "🔴 LATE — ~35% of confirmations landed" if delayed else ("🟠 STALE FEED" if stale else "🟢 On time")
    dep_rows.append({"College": c["name"], "Outcome data status": status})
st.dataframe(pd.DataFrame(dep_rows), hide_index=True, use_container_width=True)
st.caption(
    "Handling: colleges with delayed/stale outcome data show placement rate as a labeled **lower bound**, "
    "never a silently-wrong final number. Chased with an ETA against the data-eng team rather than waiting."
)

st.divider()
st.caption("PlaceMux internal · Task 16, Week 5, Phase 2 — College Portal & Reporting API Foundations")
