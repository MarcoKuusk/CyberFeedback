# Phase 1 — Multi-Respondent Data Model (Implementation Plan)

> Detailed plan for Phase 1 of [ROADMAP.md](ROADMAP.md). This is the prerequisite for everything org-facing.

## Objective

Replace the single-file-per-report-type storage with per-respondent records keyed by **organization → campaign → track → respondent**, so many people can submit to the same campaign without overwriting each other, and each submission can be retrieved and reported on individually.

**The bug this fixes:** today every save writes `data/{type}_assessment.json` ([server.py:20-21](../src/server.py#L20-L21)) and `/generateFeedback` re-reads that one file with no body ([scripts.js:423](../src/webinterface/scripts.js#L423)), so respondent #2 overwrites #1 and the PDF reflects whoever saved last. The same overwrite exists on the output side — one fixed `{type}_feedback_report.pdf` ([server.py:129-134](../src/server.py#L129-L134)).

## Exit criteria (done when)

- 30 submissions to one campaign/track produce 30 distinct stored records and 30 distinct PDFs — no overwrites.
- A submission and its report are retrievable by `(campaign_id, track, respondent_id)`.
- Every request-derived path segment is validated and confirmed inside its base directory.
- Existing local data is migrated into a seeded campaign with no loss.
- `pytest` covers the happy path, the no-overwrite guarantee, and adversarial path inputs.

---

## 1. Data model

### Directory layout

```
src/data/
  campaigns.json                                  # registry (gitignored, lives under data/)
  {org_slug}/{campaign_id}/{track}/{respondent_id}.json

src/Generated_PDF_Report/
  {org_slug}/{campaign_id}/{track}/{respondent_id}.pdf
```

`track` ∈ `{employee, organization}` (the existing `ALLOWED_REPORT_TYPES`). The employee track holds many respondents; the organization track holds one or a few leadership respondents.

### Campaign registry (`campaigns.json`)

```json
{
  "campaigns": {
    "<campaign_id>": {
      "campaign_id": "3f5e...32hex",
      "org_name": "Acme Ltd",
      "org_slug": "acme-ltd",
      "tracks": ["employee", "organization"],
      "status": "open",
      "created_at": "2026-06-20T10:00:00Z"
    }
  }
}
```

`tokens` (per-track access tokens) are **deliberately not here yet** — that field arrives in Phase 3 with tokenized links. Written with an atomic write (temp file + `os.replace`) so a concurrent reader never sees a half-written registry.

### Identifier rules (the security backbone)

| Segment | Source | Validation | Why safe |
|---|---|---|---|
| `org_slug` | derived from `org_name` once, at creation | `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$` | Never taken from request paths — looked up from the trusted registry by `campaign_id` |
| `campaign_id` | server-generated `uuid4().hex` | `^[0-9a-f]{32}$` | Opaque, unguessable, no user input |
| `respondent_id` | server-generated `uuid4().hex` at submit | `^[0-9a-f]{32}$` | Opaque, no user input |
| `track` | request path | must be in `ALLOWED_REPORT_TYPES` | Allowlist |

**Key design point:** request URLs carry `campaign_id` (opaque), never `org_slug`. The slug is resolved from the registry, so the most user-influenced segment never reaches path construction directly. Server-generated IDs + allowlisted track + containment check = defense in depth.

### Concurrency

Per-respondent filenames are unique by construction, so concurrent submissions never contend on the same file — this is the whole point of the model. The only shared mutable file is `campaigns.json`, written rarely (campaign creation) via atomic replace. This is sufficient for the Flask dev server now and for the WSGI server in Phase 4.

---

## 2. New module: `src/campaign_store.py`

Centralizes all path construction, validation, and I/O so [server.py](../src/server.py) stays thin and the logic is unit-testable in isolation. Proposed surface:

```python
def slugify(org_name: str) -> str: ...
def create_campaign(org_name: str, tracks: list[str]) -> dict: ...
def get_campaign(campaign_id: str) -> dict | None: ...
def list_campaigns() -> list[dict]: ...

def save_submission(campaign_id, track, payload) -> str:   # returns respondent_id
def load_submission(campaign_id, track, respondent_id) -> tuple[list, dict]:
def report_path(campaign_id, track, respondent_id) -> str: # PDF output path

def _safe_join(base, *parts) -> str: ...                   # the single containment guard
```

The one guard every path flows through:

```python
def _safe_join(base, *parts):
    base_abs = os.path.abspath(base)
    candidate = os.path.abspath(os.path.join(base_abs, *parts))
    if candidate != base_abs and not candidate.startswith(base_abs + os.sep):
        raise ValueError("Path escapes base directory.")
    return candidate
```

---

## 3. API changes

| Action | Today | Phase 1 |
|---|---|---|
| Load questionnaire | `GET /api/questionnaire/<track>` | unchanged (questionnaires are global config) |
| Create campaign | — | `POST /api/campaigns` → `{campaign_id, tracks, ...}` |
| List campaigns | — | `GET /api/campaigns` |
| Save submission | `POST /saveAssessmentData/<track>` | `POST /saveAssessmentData/<campaign_id>/<track>` → `{respondent_id}` |
| Generate report | `POST /generateFeedback/<track>` (no body) | `POST /generateFeedback/<campaign_id>/<track>/<respondent_id>` |
| Download report | `GET /downloadReport/<track>` | `GET /downloadReport/<campaign_id>/<track>/<respondent_id>` |

`save_submission` generates the `respondent_id` server-side and returns it; the client holds it for the subsequent generate/download calls.

> ⚠️ `POST /api/campaigns` is **unauthenticated in Phase 1** and acceptable only because the app binds `127.0.0.1` for local dev ([server.py:143](../src/server.py#L143)). It **must** be auth-gated in Phase 3 before any hosting (Phase 4). Flagged here so it isn't forgotten.

---

## 4. Server changes ([server.py](../src/server.py))

- Add `_validate_campaign(payload)` returning `(bool, str)`, matching the existing `_validate_payload` convention ([server.py:39-60](../src/server.py#L39-L60)): require `org_name` (non-empty str) and `tracks` (non-empty subset of `ALLOWED_REPORT_TYPES`).
- Rewrite `save_assessment_data`, `generate_feedback`, `download_report` to take the new path params, validate `track` against the allowlist, validate id formats, then delegate to `campaign_store`. Keep `_json_error` for all client errors and keep tracebacks server-side only.
- Catch `ValueError` from `_safe_join` / unknown campaign and return a generic `400`/`404` — never echo the path.

## 5. `main.py` change ([main.py](../src/main.py))

`generate_report` currently hardcodes the output name `f"{report_type}_feedback_report.pdf"` ([main.py:323](../src/main.py#L323)). Parameterize it to accept an explicit output path (supplied by `campaign_store.report_path`). The PDF *layout* is unchanged in Phase 1 — the per-person report stays as-is; org rollup layouts are Phase 2.

## 6. Frontend changes ([scripts.js](../src/webinterface/scripts.js))

- Read `campaign_id` from the URL query string at load; store it in `state`. (Phase 3 replaces this with tokenized links; for now a `?campaign=<id>` param, with a dev fallback that creates/uses a seeded campaign.)
- `submitAssessment` → `POST /saveAssessmentData/{campaign_id}/{track}`; store the returned `respondent_id` in `state` ([scripts.js:265-287](../src/webinterface/scripts.js#L265-L287)).
- `generateAndDownloadReport` → `POST /generateFeedback/{campaign_id}/{track}/{respondent_id}` then download `/downloadReport/{campaign_id}/{track}/{respondent_id}` ([scripts.js:413-442](../src/webinterface/scripts.js#L413-L442)).
- The client-side summary view (`summarizeAssessment`) is untouched.

## 7. Migration (`scripts/migrate_to_campaigns.py`)

One-time script: if legacy `data/{type}_assessment.json` files exist, create a seeded campaign (`org_name: "Legacy import"`) and move each file to `…/{campaign_id}/{track}/{respondent_id}.json`. Idempotent and safe to re-run (no-op if already migrated). Local data dirs are gitignored, so this never touches the repo.

---

## 8. Security checklist (mapped to CLAUDE.md)

- [ ] Every path segment validated against its pattern **and** passed through `_safe_join` containment check.
- [ ] `track` validated against `ALLOWED_REPORT_TYPES` before any file I/O.
- [ ] All client errors generic via `_json_error`; tracebacks stay server-side.
- [ ] New endpoints follow the `_validate_*` `(bool, str)` convention.
- [ ] Questionnaire JSON still treated as read-only.
- [ ] No assessment content or PII written to logs.
- [ ] `campaigns.json` and all submission data remain under gitignored `src/data/`.
- [ ] `POST /api/campaigns` flagged for auth-gating in Phase 3 before hosting.

## 9. Testing plan (`pytest`, per CLAUDE.md — real fixtures, mock OpenAI at the boundary)

- `create_campaign` → registry entry with valid slug; `get`/`list` round-trip.
- **No-overwrite guarantee:** two `save_submission` calls to the same `(campaign_id, track)` create two files; both load back correctly.
- `save_submission` → `load_submission` round-trip preserves responses + metadata.
- `_validate_campaign` accepts valid payloads, rejects empty `org_name`, bad `tracks`, non-allowlist tracks.
- **Adversarial paths:** `respondent_id`/`campaign_id` like `../../etc`, absolute paths, URL-encoded traversal, and bad-format ids are all rejected before touching disk.
- `report_path` lands inside `Generated_PDF_Report` and nowhere else.

## 10. Out of scope (deferred)

- Tokenized no-login access links and admin auth → **Phase 3**
- Employee aggregate, org self-assessment rollup, combined gap report → **Phase 2**
- Async/background report generation, retries → **Phase 5**
- Any database — stays JSON per CLAUDE.md until the documented threshold is explicitly crossed

---

## 11. Task order (each independently testable)

1. `campaign_store.py`: `_safe_join`, `slugify`, registry read/write (atomic), id validation. + unit tests.
2. `create_campaign` / `get_campaign` / `list_campaigns` + tests.
3. `save_submission` / `load_submission` / `report_path` + no-overwrite test.
4. Parameterize `generate_report` output path in `main.py`.
5. Rewrite the three endpoints + add `_validate_campaign` + campaign create/list endpoints.
6. Frontend: campaign context, respondent_id handling, new URLs.
7. `scripts/migrate_to_campaigns.py` + run against local data.
8. Full adversarial-path test pass; manual end-to-end with two concurrent submissions.
