# 20-Day Ship Plan — Pilot #1

**Target date:** 2026-08-30 (day 20 from 2026-08-10)

**Definition of shipped:** one real organization completes both tracks — leadership does the org self-assessment, staff do the employee assessment — on a local deployment you operate on-site. Every employee gets their own private PDF. Leadership gets three org-facing reports. You walk away with a clean, anonymized research dataset for the thesis.

This plan supersedes the *sequencing* in [ROADMAP.md](ROADMAP.md). It does not supersede its architecture: Block 1 below implements [PHASE1_PLAN.md](PHASE1_PLAN.md) with three amendments (§ Amendments). Phases 4 and 6 of the roadmap are explicitly out of scope for day 20.

---

## What changed from the roadmap, and why

Four decisions reshape the plan:

1. **One org at a time, local, you on-site.** Hosting leaves the critical path entirely. No Docker, no HTTPS/reverse proxy, no cloud, no multi-tenant concurrency pressure. This is what makes 20 days credible — it buys back roughly 4 days versus a hosted launch.
2. **It's thesis research.** A separate anonymized research dataset becomes a **first-class deliverable**, not a Phase 6 nicety. It also pulls informed consent and a data-handling statement into scope on day 1 rather than day 19.
3. **All four reports must exist.** Including the combined gap report — which means the questionnaire crosswalk (§ Risk 1) is now on the critical path. This is the plan's largest unknown.
4. **EN ships, ET is plumbed.** Locale is threaded through the data model, campaign registry, prompts, and PDF pipeline now; only English *content* ships. Estonian becomes a translation task, not a refactor.

---

## Day 0 — Hygiene (done)

Small, unambiguous, no design decisions. Cleared before Block 1 so the foundation work starts on a clean base.

- Pin every dependency to the versions currently installed and known-working; drop the five declared-but-never-imported packages (`pandas`, `numpy`, `jsonschema`, `pymupdf`, `flask-cors`) and the duplicate `flask` entry. An unpinned install breaking on launch day is a real and entirely avoidable failure.
- Delete `src/config.json` — it holds an API-key placeholder no code reads, and a file named that is an invitation to paste a real key into it.
- Fix the mojibake at [scripts.js:324](../src/webinterface/scripts.js#L324) and [scripts.js:326](../src/webinterface/scripts.js#L326) (`�` where an en dash belongs) — user-visible in the results screen.
- **Do not delete `src/data/cyber_readiness.db`** — inspecting it changed the plan (§ Recovered from the earlier prototype).
- Add `pytest` and a `tests/` scaffold so Block 1 can be test-driven from its first commit. Nine tests now pin the scoring engine's arithmetic and band boundaries — `analyze_assessment` is the foundation of the aggregate, the gap report, and the research export, so it must not shift silently underneath them.

## Recovered from the earlier prototype

`src/data/cyber_readiness.db` is not stale junk. It is a June 2026 implementation that already had the architecture this roadmap proposes — `projects` with `preferred_language`, per-assessment `language`, and `generated_reports` tracking `ai_used`/`ai_model`/`ai_status`. Three things follow:

- **A complete Estonian translation of the 34-question organization questionnaire**, extracted to `src/Question_And_Data/organization_questionnaire.et.json`. Verified against the EN source: 34/34 questions, identical category order, identical score vectors, translated answer options. Category keys were deliberately left in English, which confirms scoring and the crosswalk are locale-independent — only display text is translated. This removes most of day 14's work. **The employee questionnaire has no ET translation yet** — that remains real work.
- **50 Estonian artifacts** — 20 `policy`, 24 `training`, 5 `training_lesson`, 1 `training_quiz` — from a policy/training-generation feature the current rewrite dropped entirely. Out of scope for day 20, but worth knowing it exists before rebuilding anything similar, and possibly relevant to thesis scope.
- **Three completed organization assessments** from four Estonian companies (services and cleaning, 10–12 employees). No contact names or emails were ever filled in, so there is no PII cleanup burden — but this may be usable pilot data for the thesis. Check before discarding.

Because the file is gitignored and untracked, a routine cleanup would have destroyed all of this irreversibly. The extracted questionnaire is now in the repo; consider committing a copy of the artifacts you care about too.

---

## Block 1 — Days 1–5: multi-respondent foundation

**Why first:** three confidentiality bugs make the current build unusable with more than one respondent, and every deliverable below depends on per-respondent storage.

- [server.py:92-94](../src/server.py#L92-L94) — all saves write one file per report type; respondent #2 destroys #1.
- [server.py:99-113](../src/server.py#L99-L113) — `/generateFeedback` takes no body and re-reads that shared file, so B's report can be built from A's answers.
- [server.py:129](../src/server.py#L129) — one fixed PDF filename, so `/downloadReport` can serve A's report to B.

In a pilot collecting candid admissions of weak security habits tied to a named employer, the third one is a personal-data breach, not an inconvenience. Nothing ships until this block is done.

| Day | Work | Output |
|---|---|---|
| 1–2 | `src/campaign_store.py`: `_safe_join`, `slugify`, atomic registry write, id-format validation, `create/get/list_campaign`, `save/load_submission`, `report_path`. Adversarial path tests from the start. | Storage layer + passing tests |
| 3 | Parameterize the hardcoded output name at [main.py:323](../src/main.py#L323); rewrite the three endpoints onto campaign-scoped URLs; add `_validate_campaign()` per the existing `(bool, str)` convention. | New API surface |
| 4 | Frontend: campaign context from the URL, hold `respondent_id` in state, new endpoint URLs, **consent screen before question 1**. | Working respondent flow |
| 5 | Migration script for existing local data; end-to-end run with several simulated respondents; fix fallout. | **M1** |

**M1 — exit criteria:** 30 submissions to one campaign produce 30 distinct records and 30 distinct PDFs, each retrievable by `(campaign_id, track, respondent_id)`, with no crossover between respondents. Every request-derived path segment validated and confirmed inside its base directory.

### Amendments to PHASE1_PLAN.md

Three fields the original plan doesn't carry, added now because retrofitting them later touches every stored record:

- **`locale`** on the campaign (`en` | `et`) — the EN-first-then-ET plumbing.
- **`consent`** on each submission — timestamp and the version of the consent text agreed to. Required for thesis use of the data.
- **`submitted_at`** on each submission — needed for the research dataset and participation tracking.

---

## Block 2 — Days 6–10: the four reports

| Day | Work |
|---|---|
| 6 | `aggregate_assessment()` in [report_analysis.py](../src/utils/report_analysis.py) — mean overall score, per-category distribution, maturity-band counts, top gaps, participation. Minimum-N suppression built in, not bolted on. |
| 7 | Employee aggregate PDF layout (distinct from the per-person report). |
| 8 | **Category crosswalk** (needs your domain review) + `compute_gap()`. |
| 9 | Gap report PDF layout; org self-assessment report framing. |
| 10 | Critical read-through: generate all four from synthetic data, read them as a client would, fix prompt and layout problems. |

**M2 — exit criteria:** from one campaign you can produce all four reports — individual (private), employee aggregate (anonymized), org self-assessment, and combined gap — and none of them identifies an individual employee.

**Anonymization rule:** no category breakdown renders in any leadership-facing report below **N = 5** respondents. With a small pilot org this will bite; better it bites you in testing than a client discovering that a 3-person team's "aggregate" identifies people.

---

## Block 3 — Days 11–15: research data, reliability, operability

| Day | Work |
|---|---|
| 11 | **Research export** — `responses_long.csv` (one row per respondent × question, with score, max, ratio, category), `respondents.csv` (overall + per-category scores, maturity band, track, consent, timestamp), `campaigns.csv` (org pseudonym, participation, locale). Opaque respondent ids and an org pseudonym (`org_1`) so the thesis never names the client. Stdlib `csv` — no pandas needed. |
| 12 | Reliability: timeout + retry on the OpenAI call ([openai_response_client.py:38](../src/Feedback_Generators/openai_response_client.py#L38) has neither); serve under `waitress` with threads; move individual-report generation off the request path; add a batch regenerate script. |
| 13 | Admin page: create a campaign, watch participation per track, trigger rollups, download everything. (Falls back to a CLI script if the day is tight.) |
| 14 | ET plumbing: locale-aware questionnaire loading, language directive in the prompts. The org ET questionnaire already exists (§ Recovered); the **employee** ET translation is the remaining content work. Font risk already retired — all of `õ ä ö ü š ž Õ Ä Ö Ü Š Ž` round-trip through ReportLab's base-14 fonts, verified by text extraction, so no font embedding is needed. |
| 15 | Privacy and ops: data-handling one-pager for the client, "delete this org's data" script, no-PII log audit. |

**M3 — feature freeze at end of day 15.** Everything after this is verification and fixes.

**Why reliability moved up from roadmap Phase 5:** 30 employees means 30 sequential OpenAI calls. On the current single-threaded dev server with no timeout, one hung call blocks every other respondent in the room. The API cost is trivial (a few dollars); the wall-clock and blocking behaviour are not.

---

## Block 4 — Days 16–20: rehearsal and hardening

**No new features. This block is why the plan is credible.**

| Day | Work |
|---|---|
| 16 | Full security review pass over everything built, against the CLAUDE.md rules; fix findings. |
| 17 | **Dress rehearsal** — simulate the real pilot end to end, 10+ respondents from a second machine over the network. Time every step. |
| 18 | Fix everything the rehearsal surfaced. |
| 19 | Pilot pack: consent form, participant instructions, your on-site runbook, README rewrite. |
| 20 | **Buffer. Schedule nothing here.** |

---

## Risks, largest first

1. **The gap-report crosswalk needs your judgment, not mine.** The two questionnaires don't align: 5 employee categories against 11 org categories. A defensible mapping is roughly — Password & Access ↔ Identity & Access Management; Phishing & Email ↔ Security Awareness & Training; Device & Data ↔ Network & Endpoint + Data Classification; Remote Work ↔ Remote Work Security; Incident Reporting ↔ Incident Response & BC. Five org categories (Backup, Compliance, Physical, Patch Management, Third-Party Risk) have **no employee counterpart** and must render as "leadership-only — no staff signal" rather than a fake zero. Comparing a 5-point employee scale against the org scale also needs an explicit normalization choice. Get this reviewed on day 8; it is both the gap report's foundation and a defensible methodological contribution for the thesis.

2. **Ethics approval may have a longer lead time than the build.** Human-subjects research at most universities needs review board sign-off, and that can take weeks. Nothing in this plan unblocks it. **Start the application on day 0, in parallel** — it is the one item that can make the pilot impossible while the code is finished and working.

3. **How employees reach the app is undecided.** Local deployment still needs 30 people to open it. Recommended default: `waitress` bound to the org's LAN with a campaign token in the URL, run during an on-site session. Alternatives are a temporary tunnel or a handful of devices you bring. Roughly half a day either way, but it changes the day-17 rehearsal setup — decide before day 12.

4. **Report quality is subjective and expands to fill available time.** It is deliberately boxed into day 10 and day 18. Resist polishing outside those days.

5. **One org, one shot.** A pilot that goes badly is hard to re-run with the same client. Day 17's rehearsal is the mitigation and is not optional.

## Out of scope for day 20

Hosting and containerization, self-serve signup and accounts, cross-org benchmarking, trend-over-time, per-org PDF branding, any database. Local JSON holds fine at this scale; revisit only at the threshold documented in the roadmap's Phase 0.
