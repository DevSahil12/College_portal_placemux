# PlaceMux — College Dashboard (Task 16, Week 5, Phase 2)

Streamlit dashboard for the College Portal & Reporting API Foundations task.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`. No external services or API keys needed —
the event log is generated in-process by `data_gen.py` on first load.

## Files

| File | Purpose |
|---|---|
| `app.py` | The dashboard UI (Streamlit) |
| `metrics.py` | Event → metric → decision logic. Single source of truth for every number shown. Also owns the tenant-isolation guard. |
| `data_gen.py` | Generates the sample event log — 5 colleges, ~2,400 events, with **intentional** data-quality flaws seeded in (see below) |
| `spec/College_Dashboard_Spec.md` | The metric dictionary / dashboard spec — the hand-off "blueprint" deliverable |

## What's deliberately broken in the sample data (and why)

A dashboard that only ever shows clean happy-path data doesn't prove its checks work. So:

- **Kanpur Rural Engineering College** — event feed has gone stale (nothing landed in >24h) → freshness check FAILs for this college only.
- **Jaipur School of Technology** — a tracking double-fire bug creates one abnormal spike day in application volume → spike/sanity check FLAGs it.
- **Bhopal Institute of Management & Tech** — the upstream "Outcome data" feed (placement confirmations) is running behind, per the task brief's stated dependency → placement rate for this college is shown as a labeled lower bound, not a false final number.
- **Delhi Institute of Applied Sciences** — a landing-pipeline retry bug duplicates ~0.6% of rows → duplicate-rate check FAILs for this college only.

Every other college and check passes cleanly, so the failures you see are signal, not noise.

## How this maps to the scoring rubric

| Rubric line (100 pts) | Where it's covered |
|---|---|
| Core deliverable built, working & demoable (50) | Full funnel dashboard, live metrics, runs end-to-end with one command |
| Real-data quality & correctness (20) | ~2,400-row seeded dataset with real funnel drop-off ratios, not a toy dataset; 4 independent, isolated data-quality flaws for the checks to catch |
| Live verification & evidence (15) | "Fire event now" button lands a real event and every number recomputes live in front of the viewer, not a claim |
| Dependency, failure & edge-case handling (15) | Tenant isolation is enforced and provably tested live; delayed "Outcome data" upstream dependency is surfaced with a caveat instead of a silently wrong number; stale/duplicate feeds fail loudly instead of being averaged over |

## Demo script (2 minutes)

1. Open as Delhi Institute → point out the 🔴 duplicate-rate FAIL and explain the source (`metrics.py::duplicate_rate_check`).
2. Switch to Kanpur → point out the freshness FAIL, explain what it means (stop trusting these numbers until the pipe is fixed).
3. Switch to Jaipur → show the flagged spike day on the trend chart.
4. Switch to Bhopal → show placement rate labeled as a partial lower bound because of the delayed outcome-data dependency.
5. Pick any college → click "Attempt cross-tenant read" against another college → show the isolation log proving it was blocked.
6. Click "Fire event now" → show a metric change live on screen.
