# College Dashboard — Spec & Metric Dictionary

**Task 16 · Week 5 · Phase 2 · College Portal & Reporting API Foundations**
**Owner:** Data Analyst · **Status:** Spec ready, reference implementation demoable
**Hands off to:** Backend/portal team (for the real reporting API), Founder (for weekly review)

---

## 1. Purpose

One dashboard per college placement officer, scoped strictly to their own college, answering: *is placement working right now, and what should we do next.* Every number must be traceable to a real event and tied to a decision. No vanity metrics.

## 2. Audience & access model

- **Primary user:** a college's placement officer, logged in as that college only.
- **Access rule:** `requester_college_id == target_college_id`, enforced at the query layer (`metrics.scope_events`), not just hidden in the UI. A logged-in officer's requests for another college's data are rejected with an explicit error, not silently empty data.
- **Secondary user:** PlaceMux founder/ops, who can see the isolation log and dependency status across all colleges (superset view — out of scope for this task, flagged for the portal team).

## 3. Event sources (the "define → emit → land" pipeline)

| Event type | Fired when | Required fields |
|---|---|---|
| `application_submitted` | Student submits an application | `student_id`, `college_id`, `branch` |
| `interview_scheduled` | A company schedules an interview slot | + `company` |
| `interview_completed` | The interview actually happens | + `company` |
| `offer_extended` | Company extends an offer | + `company`, `ctc_lpa` |
| `placement_confirmed` | Student accepts and confirms | + `company`, `ctc_lpa` |

These land in a single append-only event table. Metrics are computed by aggregating this table — never by hand-maintained spreadsheets — so "why does it say that" always resolves to a specific query.

## 4. Metric dictionary

| Metric | Definition | Source | Decision it drives | Owner function |
|---|---|---|---|---|
| Funnel counts | Distinct students per event type, this college | Event log | Which stage has the steepest drop-off — intervene there first | `funnel_counts` |
| Placement rate | `placement_confirmed` students ÷ eligible roster | Event log ÷ roster | If trending low with the window closing, escalate to outreach for more company drives | `placement_rate` |
| Interview→Offer conversion | Distinct offered ÷ distinct interviewed-completed | Event log | Low rate → run mock-interview prep, not more sourcing | `conversion_rate` |
| Scheduled→Completed conversion | Distinct completed ÷ distinct scheduled | Event log | Low rate → students are no-showing slots, fix scheduling process | `conversion_rate` |
| Average CTC | Mean `ctc_lpa` on confirmed placements | Event log | Below-market for tier → need stronger companies in pipeline, not just more volume | `average_ctc` |
| Freshness | Age of the newest landed event for this college | `max(ts)` | Past 24h SLA → stop trusting this college's numbers, page data-eng | `freshness_check` |
| Null-field rate | Missing `company` on events that require it | Event log | ≥3% → block from being shown as "complete"; flag to data-eng | `null_rate_check` |
| Duplicate rate | Share of repeated `event_id` | Event log | Any meaningful rate → de-dupe before it feeds any external report | `duplicate_rate_check` |
| Spike/sanity check | Z-score anomaly on daily application volume | Event log, trailing window | Flagged day excluded from trend reporting until confirmed real | `spike_check` |

## 5. Data-quality thresholds

| Check | Pass | Warn | Fail |
|---|---|---|---|
| Freshness | ≤ 24h | — | > 24h |
| Null-field rate | < 1% | 1–3% | ≥ 3% |
| Duplicate rate | ≤ 0.1% | — | > 0.1% |
| Spike (\|z-score\|) | < 3 | — | ≥ 3 |

Thresholds live in code (`metrics.py`) so they version alongside the metrics they gate, not in a slide.

## 6. Known upstream dependency

**Outcome data** (placement confirmations) can arrive later than the offer/interview funnel. When a college's outcome feed is behind:

- Placement rate is shown labeled as a **lower bound**, with the confidence state exposed on the card — never silently presented as final.
- The dependency panel shows per-college feed status (on-time / stale / late) so a lagging feed is visible before someone builds a decision on top of a wrong number.
- Chase protocol: agree an ETA with the upstream team as soon as a feed is flagged late — don't wait silently.

## 7. Definition of done (this task)

- [x] Spec above is written and reviewed.
- [x] Reference dashboard (`app.py`) is built, running end-to-end on real (seeded, non-toy) sample data.
- [x] Every metric traces to a named source function; no metric exists without a stated decision.
- [x] Freshness/null/duplicate/spike checks implemented and demonstrably differentiate good vs. bad feeds.
- [x] Tenant isolation implemented and provably tested live in-app, not just asserted.
- [x] Delayed upstream dependency (Outcome data) surfaced with a caveat, not hidden.

## 8. Explicit hand-off to next team

- **What they're getting:** this spec, the reference Streamlit implementation, and the metric/threshold definitions in `metrics.py`.
- **What they still need to build:** the production reporting API (`GET /colleges/{id}/metrics`) implementing the same tenant-scoping rule as `scope_events`, backed by the real product database instead of the generator in `data_gen.py`.
- **What must not change without data-analyst sign-off:** the metric definitions and thresholds in Sections 4–5 — changing these silently changes what "good" means without anyone deciding it should.
