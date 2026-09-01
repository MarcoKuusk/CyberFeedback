# Phase 2 — Organizational Reports: Aggregate, Self-Assessment, and the Gap (Implementation Plan)

> **Status:** the implementation described here has landed and is merged into `main`.
> **Sequencing is superseded by [SHIP_PLAN.md](SHIP_PLAN.md)**, which is the live plan;
> this document survives as the design rationale for the org-level reports (Block 2 there).
>
> Detailed plan for Phase 2 of [ROADMAP.md](ROADMAP.md). Phase 1 ([PHASE1_PLAN.md](PHASE1_PLAN.md)) made a campaign able to *hold* many respondents across two tracks. Phase 2 turns those stored submissions into **the three reports the product is actually sold on**.

## Objective

From a single campaign's two tracks, produce the org-facing artifacts:

1. **Employee aggregate** — a team-wide human-risk view across all employee-track respondents (what people *actually do*).
2. **Organizational self-assessment** — the top-down control-maturity report from the organization track (what leadership *believes is in place*). This already works per-respondent; Phase 2 just surfaces it as the campaign-level leadership report.
3. **Combined / gap report** — the differentiated artifact: stated control maturity next to observed staff behavior, with the divergences called out ("leadership rates training as mature; 60% of staff scored weak on phishing").

The per-employee private report already exists (Phase 1) and is unchanged here except that Phase 2 confirms its answers never surface in any org-level output.

**What makes this phase non-trivial:** the two questionnaires use *different category taxonomies* (confirmed below), so the gap report is not a row-by-row score diff — it requires an explicit control→behavior mapping. And every org-level output is anonymized: no individual respondent is identifiable, and no breakdown is shown below a minimum participation threshold.

## Exit criteria (done when)

- For a campaign with an employee track of N respondents, `/generateOrgReport/{campaign_id}` with `mode=aggregate` produces one team-wide PDF: mean score, per-category distribution, maturity-band counts, top gaps, participation count — **identifying no individual**.
- `mode=organization` produces the leadership self-assessment report from the organization track.
- `mode=combined` produces a report pairing stated control maturity against observed behavior per mapped category, flagging the largest gaps.
- When the employee track has fewer than `MIN_AGGREGATE_N` respondents, per-category breakdowns are **suppressed** (not just hidden in the UI — never assembled server-side) and the report says so.
- No respondent id, name, free-text answer, or other PII appears in any org-level PDF, AI prompt, or log line.
- Every new path/identifier (`mode`) is allowlisted and every output path passes through `_safe_join`.
- `pytest` covers aggregate math, min-N suppression, the category mapping, the `mode` allowlist, and adversarial inputs — with OpenAI mocked at the generator boundary.

---

## 1. The category-mapping problem (design decision up front)

The two questionnaires do **not** share categories (extracted from `Question_And_Data/`):

| Employee track (behavior) | Organization track (control) |
|---|---|
| Password & Access Management | Identity & Access Management |
| Phishing Awareness & Email Security | Security Awareness & Training |
| Device & Data Security | Network & Endpoint Security · Data Classification & Protection |
| Remote Work & Public Network Security | Remote Work Security |
| Incident Reporting & Cybersecurity Culture | Incident Response & Business Continuity |
| *(no behavioral counterpart)* | Software & Patch Management · Backup & Recovery · Compliance & Regulatory Alignment · Physical Security · Third-Party Risk |

So the gap report pairs **only the five mappable categories**. Org-only controls (patching, backups, compliance, physical, third-party) are reported in the *organizational* report but explicitly flagged in the gap report as **"control stated — no behavioral signal collected"** rather than silently dropped. This honest treatment is itself part of the pitch (it shows what an employee campaign can and can't measure).

**Implementation:** a single declared mapping table, the source of truth for the gap report:

```python
# utils/report_analysis.py  — control category -> employee behavior category
CONTROL_TO_BEHAVIOR = {
    "Identity & Access Management": "Password & Access Management",
    "Security Awareness & Training": "Phishing Awareness & Email Security",
    "Remote Work Security": "Remote Work & Public Network Security",
    "Incident Response & Business Continuity": "Incident Reporting & Cybersecurity Culture",
    "Network & Endpoint Security": "Device & Data Security",
    "Data Classification & Protection": "Device & Data Security",
}
CONTROL_ONLY = {  # org controls with no behavioral mirror — reported, never faked
    "Software & Patch Management", "Backup & Recovery",
    "Compliance & Regulatory Alignment", "Physical Security", "Third-Party Risk",
}
```

Keeping the map as data (not scattered `if` branches) means questionnaire edits are a one-line change and the map is directly unit-testable. It lives next to `infer_context_signals` ([report_analysis.py:29](../src/utils/report_analysis.py#L29)).

---

## 2. Analysis layer — new functions in `utils/report_analysis.py`

The per-submission engine `analyze_assessment()` ([report_analysis.py:76](../src/utils/report_analysis.py#L76)) is reused unchanged. Phase 2 adds two pure functions on top of it (no I/O, no OpenAI — trivially testable).

### `aggregate_assessment(submissions, report_type="employee") -> dict`

Input: a list of per-respondent `assessment_data` lists (the employee track). Runs `analyze_assessment()` on each, then rolls up:

- `respondent_count` (N).
- `mean_overall_score` and band: reuse `get_maturity_label` ([report_analysis.py:14](../src/utils/report_analysis.py#L14)).
- `category_means`: mean of each category score across respondents, reusing the existing `category_scores` shape ([report_analysis.py:130-133](../src/utils/report_analysis.py#L130-L133)).
- `band_distribution`: count of respondents in each `MATURITY_BANDS` ([report_analysis.py:7-11](../src/utils/report_analysis.py#L7-L11)) — overall and optionally per category.
- `gap_prevalence`: for each category, the **share** of respondents scoring "Needs Attention" — this is the human-risk headline ("48% weak on phishing"), not an average.
- `top_team_gaps`: the lowest mean categories (mirrors `top_gap_categories`).
- `common_actions`: most frequent `priority_actions` across the team (aggregate the per-respondent `Counter` logic, not raw text).
- `participation`: `respondent_count` plus, when available, `expected_count` from the campaign record (Phase 3 sets the denominator; for now N alone).

**Anonymization is enforced here, at the source:**

```python
MIN_AGGREGATE_N = 5  # below this, no per-respondent-derived breakdown leaves this function

def aggregate_assessment(submissions, report_type="employee"):
    n = len(submissions)
    if n < MIN_AGGREGATE_N:
        return {"suppressed": True, "respondent_count": n, "min_n": MIN_AGGREGATE_N}
    ...
```

A suppressed result carries the count and the threshold and **nothing else** — the breakdown is never computed, so it cannot leak through a logging or serialization mistake downstream. No names, no respondent ids, no free text ever enter the aggregate (it consumes only scored `analyze_assessment` output).

### `compare_tracks(employee_aggregate, org_summary) -> dict`

Input: the employee aggregate (above) and the organization-track `analyze_assessment` summary. Walks `CONTROL_TO_BEHAVIOR`, and for each mapped pair emits:

- `control_score` (from org `category_scores`), `behavior_score` (from `category_means`),
- `gap = control_score - behavior_score` (positive = leadership rates the control higher than staff behavior backs up — the risk signal),
- a `severity` label from the existing `get_priority_label` thresholds so language stays consistent.

Plus `control_only`: the `CONTROL_ONLY` categories present in the org summary, listed with their score and a "no behavioral signal" note. If the employee aggregate is suppressed, `compare_tracks` returns a degraded result that still renders the org self-assessment side and states why the comparison is unavailable.

---

## 3. AI generators — new classes in `Feedback_Generators/`

Follow the existing generator contract exactly ([employee_feedback_generator.py](../src/Feedback_Generators/employee_feedback_generator.py)): `__init__(data, metadata=None)`, `generate_feedback()`, prompt built from a **structured summary only**, text produced via `generate_report_text` ([openai_response_client.py:26](../src/Feedback_Generators/openai_response_client.py#L26)). No new OpenAI plumbing — reuse the shared client.

- `OrgAggregateFeedbackGenerator(aggregate)` — narrates the team-wide human-risk picture: where the team is strong, the prevalent gaps (by share, not by naming anyone), and team-level priority actions. Prompt is built from the `aggregate_assessment` dict — **never** from individual responses.
- `CombinedGapFeedbackGenerator(comparison)` — narrates the `compare_tracks` result: the largest stated-vs-observed divergences, framed for leadership, plus an honest note on control-only areas with no behavioral signal.

**Privacy rule, enforced by construction (CLAUDE.md "Prompts are built from structured assessment summaries, never from raw user text"):** these generators receive aggregated dicts, so there is no raw-text path into the prompt. Add a guard test asserting the assembled prompt contains no respondent id and no verbatim free-text answer.

Each gets a clear section template like the existing employee prompt ([employee_feedback_generator.py:46-64](../src/Feedback_Generators/employee_feedback_generator.py#L46-L64)) so `_parse_ai_sections` ([main.py:70](../src/main.py#L70)) keeps working.

---

## 4. PDF layouts — `main.py`

`save_feedback_to_pdf` ([main.py:251](../src/main.py#L251)) and the per-person flow stay as they are. Add report titles and two org layouts that **reuse** the existing styles, page chrome, and table helpers (`_build_styles`, `_draw_page_chrome`, `_metric_table`, `_category_score_table`):

- Extend `REPORT_TITLES` ([main.py:28](../src/main.py#L28)) with `org_aggregate`, `organization_rollup` (the leadership self-assessment as a campaign deliverable), and `combined`.
- `save_aggregate_to_pdf(feedback_text, aggregate, title, filename)` — participation count, overall band, a **distribution** view (band counts / gap-prevalence bars) instead of one score, top team gaps. When `aggregate["suppressed"]` is true, render a single honest page: "Aggregate withheld — N below the {min_n}-respondent anonymity threshold." Never render a partial breakdown.
- `save_gap_to_pdf(feedback_text, comparison, title, filename)` — a side-by-side table (Category · Stated control · Observed behavior · Gap) reusing the `_category_score_table` styling, the mapped categories first, control-only rows in a clearly separated, muted block.

`generate_report` ([main.py:316](../src/main.py#L316)) stays the per-respondent entry point. Add a sibling `generate_org_report(mode, campaign_id, output_path)` (details in §5) rather than overloading the existing signature.

---

## 5. Server endpoints — `server.py`

Add two endpoints alongside the Phase 1 ones, following the same `_json_error` / allowlist / `_validate_*` discipline ([server.py:26](../src/server.py#L26), [server.py:152-241](../src/server.py#L152-L241)).

| Action | Endpoint |
|---|---|
| Generate an org-level report | `POST /generateOrgReport/<campaign_id>/<mode>` |
| Download an org-level report | `GET /downloadOrgReport/<campaign_id>/<mode>` |

- `mode` ∈ `{aggregate, organization, combined}` — a new allowlist constant, validated exactly like `track` is today ([server.py:154](../src/server.py#L154)). Reject anything else with a generic 400 before any I/O.
- `campaign_id` validated via `campaign_store.is_valid_id` ([campaign_store.py:51](../src/campaign_store.py#L51)); campaign resolved via `get_campaign` (404 if missing).
- The handler gathers inputs through Phase 1 store functions only — `list_submissions` + `load_submission` ([campaign_store.py:190](../src/campaign_store.py#L190), [campaign_store.py:215](../src/campaign_store.py#L215)) — so all path building stays inside `campaign_store`'s `_safe_join` guard. The server never constructs an org-report path by hand.
- `mode=combined` requires **both** tracks enabled on the campaign; return a clear 400 if the org track (or employee track) is absent.
- Errors map like the existing generate handler ([server.py:201-208](../src/server.py#L201-L208)): `ValueError`→400, `RuntimeError`→500 (e.g. missing `OPENAI_API_KEY`), bare `Exception`→generic 500 with detail in server logs only.

### `campaign_store.py` addition

```python
ALLOWED_ORG_REPORT_MODES = {"aggregate", "organization", "combined"}

def org_report_path(campaign_id, mode) -> str:
    campaign = get_campaign(campaign_id)          # LookupError -> 404 at the edge
    if mode not in ALLOWED_ORG_REPORT_MODES:
        raise ValueError("Invalid report mode.")
    return _safe_join(GENERATED_REPORT_DIR, campaign["org_slug"], campaign_id,
                      "_org", f"{mode}.pdf")       # "_org" can't collide with a track name
```

Org rollups live under a reserved `_org/` segment (not a real respondent dir) so they never collide with the `{track}/{respondent_id}.pdf` layout. `_org` is not in `ALLOWED_TRACKS`, so it can never be produced as a track path — no ambiguity.

> ⚠️ **Auth carry-over from Phase 1.** `/generateOrgReport` and `/downloadOrgReport` expose *aggregated org data* and must be treated as leadership/admin-only. Like `/api/campaigns` ([server.py:113-117](../src/server.py#L113-L117)), they are unauthenticated in Phase 2 and acceptable **only** because the app binds `127.0.0.1`. They **must** be auth-gated in Phase 3 before any hosting (Phase 4). The min-N anonymization is the second line of defense regardless of auth.

---

## 6. Admin / frontend (light touch)

The admin panel (`webinterface/admin.*`, added in Phase 1) already lists campaigns and per-track submissions via `/api/campaigns/<id>/submissions` ([server.py:131](../src/server.py#L131)). Phase 2 adds, per campaign, three "Generate" buttons (Aggregate / Organization / Combined) that POST to `/generateOrgReport/<id>/<mode>` and then offer the download. No new questionnaire UI. Buttons for a mode whose track isn't enabled are disabled with a tooltip. The respondent count and the `MIN_AGGREGATE_N` threshold are shown so it's obvious *why* aggregate is unavailable for a small campaign.

---

## 7. Security checklist (mapped to CLAUDE.md)

- [ ] `mode` validated against `ALLOWED_ORG_REPORT_MODES` before any file I/O (allowlist, like `track`).
- [ ] All org-report output paths built only via `campaign_store.org_report_path` → `_safe_join` containment.
- [ ] No respondent id, name, or free-text answer in any aggregate/gap dict, AI prompt, PDF, or log (verified by test).
- [ ] AI prompts for org reports built from aggregated structured summaries only — no raw-response path exists.
- [ ] `MIN_AGGREGATE_N` enforced inside `aggregate_assessment` (suppressed result computes no breakdown), not merely hidden in the UI.
- [ ] New endpoints use `_json_error`; tracebacks stay server-side; `RuntimeError` (missing API key) → generic 500.
- [ ] Questionnaire JSON still read-only; `CONTROL_TO_BEHAVIOR` is code, not a runtime write.
- [ ] Org endpoints flagged for Phase 3 auth-gating before hosting.
- [ ] All generated org PDFs remain under gitignored `Generated_PDF_Report/`.

## 8. Testing plan (`pytest` — real fixtures, OpenAI mocked at the boundary)

- **Aggregate math:** N synthetic employee submissions → correct `mean_overall_score`, `category_means`, `band_distribution`, `gap_prevalence` (share, not mean).
- **Min-N suppression:** N < `MIN_AGGREGATE_N` → `{"suppressed": True, ...}` with no category data present in the returned dict.
- **Anonymity:** assert no respondent id / verbatim answer string appears anywhere in the aggregate dict, the comparison dict, or the assembled AI prompt.
- **Category mapping:** `compare_tracks` pairs exactly the mapped categories, computes `gap` with correct sign, and lists `CONTROL_ONLY` separately; handles a category missing from one side.
- **Mode allowlist:** `/generateOrgReport/<id>/<bogus>` → 400 before I/O; `combined` without both tracks → 400.
- **Path containment:** `org_report_path` lands inside `Generated_PDF_Report` for valid input and raises on a tampered mode; reuse the Phase 1 adversarial-path patterns.
- **Generator boundary:** mock `generate_report_text`; assert the two new generators call it and that `generate_org_report` writes a PDF to the given path.
- Degraded `combined` when the employee aggregate is suppressed still renders the org-self-assessment side.

## 9. Out of scope (deferred)

- Tokenized per-track links + admin auth → **Phase 3** (org endpoints are 127.0.0.1-only until then).
- Async/background generation + OpenAI retries/timeouts → **Phase 5** (aggregate over many respondents makes one synchronous call per report; acceptable at pilot scale, backgrounded in Phase 5).
- Per-org branding on PDFs → **Phase 5**.
- Cross-org benchmarking / trend over time → **Phase 6**.
- Any database — stays JSON per CLAUDE.md until the documented threshold is explicitly crossed.

---

## 10. Task order (each independently testable)

1. `CONTROL_TO_BEHAVIOR` / `CONTROL_ONLY` map + `aggregate_assessment` (incl. `MIN_AGGREGATE_N` suppression) in `report_analysis.py`. + unit tests.
2. `compare_tracks` + mapping/edge-case tests.
3. `OrgAggregateFeedbackGenerator` + `CombinedGapFeedbackGenerator` (prompts from structured dicts) + anonymity-of-prompt test (mock OpenAI).
4. `REPORT_TITLES` entries, `save_aggregate_to_pdf`, `save_gap_to_pdf`, `generate_org_report` in `main.py`.
5. `campaign_store.org_report_path` + `ALLOWED_ORG_REPORT_MODES` + path-containment tests.
6. `/generateOrgReport` + `/downloadOrgReport` endpoints + `_validate`/allowlist/error-mapping tests.
7. Admin panel: per-campaign generate/download buttons, min-N surfaced.
8. End-to-end: seed a campaign with ≥`MIN_AGGREGATE_N` employee submissions + one org submission → produce all three reports; confirm no PII anywhere and suppression fires below threshold.
