# CyberFeedback — Roadmap to Organizational Deployment

**Goal:** Take CyberFeedback from a single-user local report generator to a **managed SaaS** you can offer to real organizations — you host one deployment, and each org runs two complementary assessments: a staff-wide **employee campaign** and an **organization-level self-assessment** by leadership. You deliver a leadership-facing report — ideally one that compares the two.

**Hosting model (decided):** You host and operate it. Each org gets a per-campaign link. This drives a multi-tenant data model and per-campaign access, and keeps deployment/ops on your side rather than their IT's.

---

## The central problem this roadmap solves

Today the tool is **single-tenant, single-respondent by construction**:

- `data/{report_type}_assessment.json` is one file per report type ([server.py:20-21](../src/server.py#L20-L21)). The 2nd respondent overwrites the 1st.
- `/downloadReport/{type}` streams one fixed filename ([server.py:129-134](../src/server.py#L129-L134)).

So it can produce one excellent PDF for one person on one laptop. It cannot yet represent "an organization." And the artifact an org actually buys is **the aggregate** — "across your team, phishing awareness is weakest" — which the current model can't produce, even though the scoring engine in [report_analysis.py](../src/utils/report_analysis.py) already does the per-submission math.

Every phase below builds toward: **many respondents → one organization → one leadership report → delivered as a hosted service.**

---

## Two assessments, one organizational picture (both are selling points)

An organization gets value from CyberFeedback two ways, and the platform should deliver both within a single engagement:

- **Employee campaign — bottom-up.** Many staff complete the employee self-assessment; you aggregate them into a human-risk view. This measures *what people actually do*.
- **Organizational self-assessment — top-down.** Leadership or an SME completes the organization-level questionnaire — the existing `organization` report type ([report_analysis.py:39-46](../src/utils/report_analysis.py#L39-L46)) — covering training maturity, incident response, identity & access, etc. This measures *what the org believes is in place*.

The differentiated artifact is a **combined report that puts these side by side**. The gap between them — "leadership rates security training as mature, but 60% of staff couldn't identify a phishing email" — is an insight neither assessment produces alone, and it is the strongest part of the pitch. Sell the org self-assessment as a standalone product too: a leadership team can assess themselves as a whole without ever running an employee campaign.

The data model and reports below treat a **campaign as holding both tracks**: an employee track (many respondents → aggregated) and an organizational track (one or a few leadership respondents → the existing org report).

---

## What each stakeholder receives

- **Each employee** — their own **private** individual report (the existing per-person PDF). It is delivered only to them; their answers feed the aggregate anonymously and are never shown to leadership. This is both the participation incentive and standalone training value. *(Decided 2026-06-20.)*
- **Leadership** — the anonymized employee aggregate, their own organizational self-assessment report, and the combined gap report. Leadership is both a respondent (the org track) and the consumer of all org-level reports.
- **The organization as a whole** — a measured human-risk baseline (stated controls vs. actual behavior), and over time trend tracking and cross-org benchmarking (Phase 6).

---

## Cross-cutting thread: data trust (a sales blocker, not a nicety)

You will collect employees' candid admissions of weak security habits, tied to their employer. Orgs will not say yes without answers to: *Where does the data live? Who can see it? Can a manager single out an employee? What does OpenAI do with it? How long is it kept?*

Carry these requirements through **every** phase:
- **Anonymize the aggregate** — leadership reports never expose individual respondents; enforce a minimum-N threshold before any breakdown is shown.
- **Retention & deletion** — a documented policy and a real "delete this org's data" path.
- **Encryption at rest** + restricted access to the data directory.
- **No PII in logs** — already a CLAUDE.md rule; keep it true as endpoints grow.
- **OpenAI data posture** — confirm and document how assessment-derived prompts are handled.

---

## Phase 0 — Foundations & decisions (before code)

**Goal:** Lock the few decisions that change the architecture, so later phases don't get rebuilt.

- **Storage decision flag.** This roadmap stays on local JSON (per CLAUDE.md: no DB unless explicitly requested). That carries you through early pilots. Document the threshold where a database becomes warranted — concurrent writes across many orgs, queryable rollups, audit trails — and treat crossing it as an explicit decision, not a drift.
- **Privacy/data-trust posture** written down (the cross-cutting thread above) — this becomes a one-pager you hand to prospects.
- **Config & secrets separation** — confirm prod config never lands in the repo; `OPENAI_API_KEY` stays env-only ([openai_response_client.py:11-15](../src/Feedback_Generators/openai_response_client.py#L11-L15)).

**Done when:** the hosting, storage, and privacy decisions are written and won't be reopened mid-build.

---

## Phase 1 — Multi-respondent data model *(the unlock — nothing else works without it)*

> 📄 Detailed implementation plan: [PHASE1_PLAN.md](PHASE1_PLAN.md)

**Goal:** Store submissions keyed by organization + campaign + respondent instead of one file per type. Removes a real data-loss bug and enables everything downstream.

- New layout, with a **track** segment so one campaign holds both assessments: `data/{org_slug}/{campaign_id}/{track}/{respondent_id}.json`, where `track` is `employee` or `organization` (validated against `ALLOWED_REPORT_TYPES`).
- A lightweight campaign registry (`data/campaigns.json`): org name, campaign id, which tracks are enabled, created date, per-track access tokens, status. A campaign can enable the employee track, the organizational track, or both.
- Refactor `/saveAssessmentData` to write per-respondent within a track (server generates `respondent_id`); keep `_validate_payload()` and add `_validate_campaign()` following the `(bool, str)` convention ([server.py:39-60](../src/server.py#L39-L60)).
- **Security checkpoint:** every new path segment (`org_slug`, `campaign_id`, `track`, `respondent_id`) goes through the path-traversal guard from CLAUDE.md — validate, `abspath`, confirm containment within `DATA_DIR`.
- One-time migration of the existing single-file flow into the new layout.

**Done when:** 30 people can submit to the same campaign without overwriting each other, and each record is retrievable by campaign.

---

## Phase 2 — Organizational reports: aggregate, self-assessment, and the gap *(the artifact you sell)*

**Goal:** Turn a campaign's two tracks into the three reports that make up the pitch.

- **Employee aggregate** — `aggregate_assessment()` in [report_analysis.py](../src/utils/report_analysis.py): reuse `analyze_assessment()` per respondent, then aggregate across the employee track (mean overall score, per-category distribution, count in each maturity band, top gaps, participation rate).
- **Organizational self-assessment report** — run the existing `analyze_assessment()` on the organizational track (one or a few leadership respondents) to produce the top-down control-maturity report. This stands alone as a sellable product.
- **Combined / gap report** — the differentiated artifact: place the org's stated maturity next to the employee aggregate per category, and surface where they diverge ("leadership: training mature; staff: phishing weak"). This is the strongest deliverable; build it once both tracks produce scores.
- **Individual employee report (private)** — each respondent's existing per-person report is generated and delivered **only to that employee** (decided). It also feeds the anonymized aggregate; leadership never sees an individual's report or answers.
- New org rollup PDF layout(s) in [main.py](../src/main.py), distinct from the per-person report.
- New endpoint(s), e.g. `/generateOrgReport/{campaign_id}` with a track/mode selector.
- **Anonymization built in:** the employee aggregate carries no individual names; suppress any breakdown below the minimum-N threshold.

**Done when:** from one campaign you can produce a team-wide human-risk report, a leadership self-assessment report, and a combined report that highlights the gap between them — none of them identifying an individual employee.

---

## Phase 3 — Access & the multi-user front door

**Goal:** Let an org's staff reach *their* assessment, and let you administer campaigns. This is where minimal auth becomes justified (not speculative).

- Tokenized links per track: a broadcast **employee** link sent to all staff, and a separate **leadership** link for the organizational self-assessment — each `/c/{campaign_token}` resolves to the right questionnaire, no login.
- After an employee submits, they receive **their own** report (e.g. a one-time download or a private per-respondent link) — visible only to them, never to leadership or other staff.
- Admin view (simple auth) to create campaigns, choose which tracks are enabled, watch participation per track, trigger the rollup, download reports.
- **Security checkpoint:** tokens are unguessable and scoped to one campaign; admin routes are auth-gated; generic client errors only ([server.py:28-29](../src/server.py#L28-L29) pattern).

**Done when:** you create a campaign, send one link, staff complete it, and you generate the rollup — all without touching the filesystem by hand.

---

## Phase 4 — Production deployment (managed SaaS)

**Goal:** Run it as a real hosted service instead of the Flask dev server.

- Production WSGI server (the dev server at [server.py:143](../src/server.py#L143) is not for production); HTTPS via a reverse proxy.
- Containerize (Docker) for a repeatable deploy.
- Encryption at rest for the data directory + automated backups.
- Structured logging with **no PII**.
- Documented "delete an org's data" operation (from the Phase 0 retention policy).

**Done when:** a new org can be onboarded on a hosted URL over HTTPS, with backups and a deletion path in place.

---

## Phase 5 — Reliability & polish

**Goal:** Hold up under a real campaign and look like a product.

- **Async report generation** — the OpenAI call is synchronous in the request path ([main.py:314-325](../src/main.py#L314-L325)); background it so 30 reports don't block or time out.
- Retry + timeout handling around the OpenAI call ([openai_response_client.py:26-39](../src/Feedback_Generators/openai_response_client.py#L26-L39)).
- **Per-org branding** on the PDF (logo, org name) — cheap, high-impact; it's your product's face in the room.

**Done when:** a full-team campaign generates reliably and the output looks bespoke to the client.

---

## Phase 6 — Differentiation (later)

- **Cross-org benchmarking** — "bottom quartile for your industry," once you have several orgs.
- **Trend over time** — re-run a campaign and show movement; turns one-off assessments into a recurring engagement.

---

## Sequencing rationale

1 is a hard prerequisite for everything. 2 is the thing that makes the product *worth buying*. 3 makes it *usable by an org without you in the loop*. 4 makes it *something you can actually offer to host*. 5–6 are leverage once the core loop works. Don't reorder 1→4; 5–6 can flex based on what early pilots demand.
