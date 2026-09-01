import hmac
import json
import os
from functools import wraps
from typing import Any, Dict, Tuple

from flask import Flask, jsonify, request, send_from_directory

import campaign_store as store
from campaign_store import (
    ALLOWED_LOCALES,
    ALLOWED_ORG_REPORT_MODES,
    ALLOWED_TRACKS,
    CampaignNotFoundError,
    InvalidInputError,
)
from main import generate_org_report, generate_report
from utils.report_analysis import MIN_AGGREGATE_N

app = Flask(__name__, static_folder="webinterface")

QUESTIONNAIRE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "Question_And_Data"))

os.makedirs(store.DATA_DIR, exist_ok=True)
os.makedirs(store.REPORT_DIR, exist_ok=True)

LOOPBACK_ADDRESSES = {"127.0.0.1", "::1"}


def _questionnaire_file(track: str) -> str:
    return os.path.join(QUESTIONNAIRE_DIR, f"{track}_questionnaire.json")


def _json_error(message: str, status: int):
    return jsonify({"status": "error", "message": message}), status


# ---------------------------------------------------------------------------
# Admin gate
# ---------------------------------------------------------------------------

ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"


def _auth() -> Tuple[str | None, Dict[str, Any] | None]:
    """Resolve the caller's role, and for a viewer, the campaign it is scoped to.

    Two roles, because the operator and the client are not the same person:

    - operator (CYBERFEEDBACK_ADMIN_TOKEN) — you. Full control across every
      client, including the respondent ids that make an individual report
      retrievable.
    - viewer — the leadership of one client organization, holding that
      campaign's own `viewer_token`. Rollups and participation counts for
      **that campaign only**. Never respondent ids, never an individual report,
      and never another organization's campaign.

    Scoping the viewer credential to a single campaign is what makes it safe to
    run several client organizations on one deployment: leadership at one client
    cannot reach another's data even if they learn its campaign id.

    With no operator token configured the app is in its local development
    posture and only loopback is trusted, so a half-configured deployment cannot
    silently grant remote access.
    """
    presented = request.headers.get("X-Admin-Token", "")
    operator_token = os.getenv("CYBERFEEDBACK_ADMIN_TOKEN", "").strip()

    if not operator_token:
        if request.remote_addr in LOOPBACK_ADDRESSES:
            return ROLE_OPERATOR, None
        return None, None

    if hmac.compare_digest(presented, operator_token):
        return ROLE_OPERATOR, None

    campaign = store.resolve_viewer_token(presented)
    if campaign is not None:
        return ROLE_VIEWER, campaign
    return None, None


def _role() -> str | None:
    return _auth()[0]


def _admin_ok() -> bool:
    """True for any recognised role — used to gate the admin bundle itself."""
    return _role() is not None


def _require_admin(view):
    """Operator only."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if _role() != ROLE_OPERATOR:
            return _json_error("Not authorized.", 403)
        return view(*args, **kwargs)

    return wrapper


def _require_org_access(view):
    """Operator, or the leadership of the campaign being addressed.

    The view must take `campaign_id` as its first keyword argument; a viewer
    scoped to a different campaign is refused exactly as an unauthenticated
    caller is, so the response cannot be used to probe which ids exist.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        role, scope = _auth()
        if role == ROLE_OPERATOR:
            return view(*args, **kwargs)
        if role == ROLE_VIEWER and scope is not None:
            if scope.get("campaign_id") == kwargs.get("campaign_id"):
                return view(*args, **kwargs)
        return _json_error("Not authorized.", 403)

    return wrapper


# ---------------------------------------------------------------------------
# Validation — each returns (bool, str) per the established convention
# ---------------------------------------------------------------------------

def _validate_selected_answer(item: Dict[str, Any]) -> bool:
    selected = item.get("selectedAnswer")
    if selected is None:
        return True
    return isinstance(selected, dict) and isinstance(selected.get("option"), str) and isinstance(selected.get("score"), int)


def _validate_consent_block(consent: Any) -> Tuple[bool, str]:
    if not isinstance(consent, dict):
        return False, "Consent is required before an assessment can be saved."
    if consent.get("agreed") is not True:
        return False, "Consent is required before an assessment can be saved."
    if not isinstance(consent.get("version"), str) or not consent["version"].strip():
        return False, "Consent version is missing."
    return True, ""


def _validate_payload(payload: Any) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Request body must be an object."

    responses = payload.get("responses")
    metadata = payload.get("metadata", {})

    if not isinstance(responses, list) or not responses:
        return False, "Responses must be a non-empty list."
    if not isinstance(metadata, dict):
        return False, "Metadata must be an object."

    required_keys = {"question", "category", "answers"}
    for item in responses:
        if not isinstance(item, dict) or not required_keys.issubset(item.keys()):
            return False, "Each response must contain question, category, and answers."
        if not isinstance(item.get("answers"), list):
            return False, "Each response must include an answers list."
        if not _validate_selected_answer(item):
            return False, "Selected answers must include option and score values."

    return _validate_consent_block(payload.get("consent"))


def _validate_campaign(payload: Any) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Request body must be an object."

    org_name = payload.get("org_name")
    if not isinstance(org_name, str) or not org_name.strip():
        return False, "Organization name is required."

    tracks = payload.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        return False, "At least one track must be selected."
    if any(track not in ALLOWED_TRACKS for track in tracks):
        return False, "Invalid track requested."

    locale = payload.get("locale", "en")
    if locale not in ALLOWED_LOCALES:
        return False, "Invalid locale requested."

    return True, ""


def _public_campaign(campaign: Dict[str, Any]) -> Dict[str, Any]:
    """Projection safe to hand to anyone holding the campaign link."""
    return {
        "campaign_id": campaign["campaign_id"],
        "org_name": campaign["org_name"],
        "tracks": campaign["tracks"],
        "locale": campaign.get("locale", "en"),
        "status": campaign.get("status", "open"),
    }


def _campaign_links(campaign_id: str) -> Dict[str, Dict[str, str]]:
    """Per-track share links, absolute so they can be pasted straight into an
    email. `ensure_tokens` is idempotent, so campaigns predating link tokens
    gain them here without invalidating anything already distributed."""
    tokens = store.ensure_tokens(campaign_id)
    base = os.getenv("CYBERFEEDBACK_PUBLIC_URL", "").strip().rstrip("/") or request.url_root.rstrip("/")
    return {
        track: {"token": token, "url": f"{base}/c/{token}"}
        for track, token in tokens.items()
    }


def _viewer_credential(campaign_id: str) -> Dict[str, str]:
    """Leadership's read credential for this campaign, and where to use it."""
    base = os.getenv("CYBERFEEDBACK_PUBLIC_URL", "").strip().rstrip("/") or request.url_root.rstrip("/")
    return {"token": store.ensure_viewer_token(campaign_id), "url": f"{base}/admin"}


# ---------------------------------------------------------------------------
# Campaign management
# ---------------------------------------------------------------------------

@app.route("/api/campaigns", methods=["POST"])
@_require_admin
def create_campaign():
    payload = request.get_json(silent=True)
    is_valid, error_message = _validate_campaign(payload)
    if not is_valid:
        return _json_error(error_message, 400)

    try:
        campaign = store.create_campaign(payload["org_name"], payload["tracks"], locale=payload.get("locale", "en"))
    except InvalidInputError:
        return _json_error("Invalid campaign details.", 400)

    return jsonify(
        {
            "status": "ok",
            "campaign": _public_campaign(campaign),
            "links": _campaign_links(campaign["campaign_id"]),
            "viewer": _viewer_credential(campaign["campaign_id"]),
        }
    ), 201


@app.route("/api/campaigns/<campaign_id>/links", methods=["GET"])
@_require_admin
def get_campaign_links(campaign_id):
    """The per-track links to hand to the client.

    Operator-only: each token is a bearer credential for its questionnaire, and
    the leadership link must not be recoverable by anyone holding only the staff
    one. Backfills tokens for campaigns created before links existed.
    """
    if store.get_campaign(campaign_id) is None:
        return _json_error("Campaign not found.", 404)
    return jsonify(
        {
            "status": "ok",
            "links": _campaign_links(campaign_id),
            "viewer": _viewer_credential(campaign_id),
        }
    )


@app.route("/api/campaigns", methods=["GET"])
def list_campaigns():
    """Operator: every campaign. Viewer: only the one their token unlocks.

    Returning the viewer's own campaign here (rather than 403) is what lets
    leadership use the same admin page without being handed a way to enumerate
    other clients.
    """
    role, scope = _auth()
    if role == ROLE_OPERATOR:
        campaigns = store.list_campaigns()
    elif role == ROLE_VIEWER and scope is not None:
        campaigns = [scope]
    else:
        return _json_error("Not authorized.", 403)

    return jsonify(
        {
            "status": "ok",
            "campaigns": [
                {
                    **_public_campaign(campaign),
                    "created_at": campaign.get("created_at"),
                    "participation": {
                        track: len(store.list_respondents(campaign["campaign_id"], track))
                        for track in campaign.get("tracks", [])
                    },
                }
                for campaign in campaigns
            ],
            "role": role,
        }
    )


@app.route("/api/campaigns/<campaign_id>", methods=["GET"])
@_require_org_access
def get_campaign(campaign_id):
    """Admin detail view. Respondents no longer reach a campaign by its id —
    they resolve a per-track token through /api/link/<token> instead."""
    try:
        campaign = store.get_campaign(campaign_id)
    except InvalidInputError:
        return _json_error("Invalid campaign.", 400)
    if campaign is None:
        return _json_error("Campaign not found.", 404)
    return jsonify({"status": "ok", "campaign": _public_campaign(campaign)})


# ---------------------------------------------------------------------------
# Questionnaires — global read-only configuration
# ---------------------------------------------------------------------------

@app.route("/api/questionnaire/<track>")
def get_questionnaire(track):
    if track not in ALLOWED_TRACKS:
        return _json_error("Invalid report type.", 400)

    file_path = _questionnaire_file(track)
    if not os.path.exists(file_path):
        return _json_error("Questionnaire not found.", 404)

    with open(file_path, "r", encoding="utf-8") as file:
        questionnaire = json.load(file)
    return jsonify({"status": "ok", "questionnaire": questionnaire})


# ---------------------------------------------------------------------------
# Submissions and reports
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Respondent flow — reachable only through a per-track link token
# ---------------------------------------------------------------------------

def _resolve_link(token: str):
    """Resolve a link token to (campaign, track).

    Returns (campaign, track, None) on success, or (None, None, response) with a
    generic error the caller returns as-is.
    """
    try:
        campaign, track = store.resolve_token(token)
    except InvalidInputError:
        return None, None, _json_error("Invalid assessment link.", 400)
    except CampaignNotFoundError:
        return None, None, _json_error("This assessment link is not valid.", 404)
    return campaign, track, None


@app.route("/api/link/<token>", methods=["GET"])
def resolve_link(token):
    """Everything a respondent's browser needs to begin, and nothing more.

    The track is derived from the token rather than chosen by the client, so a
    staff link cannot open the leadership questionnaire. The other track's
    existence is not disclosed either.
    """
    campaign, track, error = _resolve_link(token)
    if error:
        return error

    return jsonify(
        {
            "status": "ok",
            "track": track,
            "campaign": {
                "org_name": campaign["org_name"],
                "locale": campaign.get("locale", "en"),
                "status": campaign.get("status", "open"),
            },
        }
    )


@app.route("/api/link/<token>/submit", methods=["POST"])
def submit_assessment(token):
    campaign, track, error = _resolve_link(token)
    if error:
        return error

    if campaign.get("status") != "open":
        return _json_error("This assessment is no longer accepting responses.", 409)

    payload = request.get_json(silent=True)
    is_valid, error_message = _validate_payload(payload)
    if not is_valid:
        return _json_error(error_message, 400)

    try:
        respondent_id = store.save_submission(campaign["campaign_id"], track, payload)
    except InvalidInputError:
        return _json_error("Assessment could not be saved.", 400)
    except CampaignNotFoundError:
        return _json_error("This assessment link is not valid.", 404)

    return jsonify(
        {
            "status": "ok",
            "message": f"{track.title()} assessment saved.",
            "respondent_id": respondent_id,
        }
    )


@app.route("/api/link/<token>/report/<respondent_id>", methods=["POST"])
def generate_respondent_report(token, respondent_id):
    campaign, track, error = _resolve_link(token)
    if error:
        return error

    try:
        assessment_data, metadata = store.load_submission(campaign["campaign_id"], track, respondent_id)
        output_path = store.report_path(campaign["campaign_id"], track, respondent_id)
    except InvalidInputError:
        return _json_error("Invalid request.", 400)
    except CampaignNotFoundError:
        return _json_error("No saved assessment found for this respondent.", 404)

    try:
        _, summary = generate_report(track, assessment_data, metadata, output_path)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except RuntimeError as exc:
        # Surfaces the missing-API-key case, which is actionable and carries no data.
        return _json_error(str(exc), 500)
    except Exception:
        app.logger.exception("Individual report generation failed for track %s", track)
        return _json_error("Report generation failed. Check server logs for details.", 500)

    return jsonify({"status": "ok", "message": "Your report is ready.", "summary": summary})


@app.route("/api/link/<token>/report/<respondent_id>", methods=["GET"])
def download_respondent_report(token, respondent_id):
    """A respondent's own report.

    Authorized by two unguessable values: the campaign link they were sent and
    the respondent id minted for their submission. The id is returned only to
    the browser that submitted, and is never exposed to leadership.
    """
    campaign, track, error = _resolve_link(token)
    if error:
        return error

    try:
        file_path = store.report_path(campaign["campaign_id"], track, respondent_id)
    except InvalidInputError:
        return _json_error("Invalid request.", 400)
    except CampaignNotFoundError:
        return _json_error("Requested report is not available yet.", 404)

    if not os.path.exists(file_path):
        return _json_error("Requested report is not available yet.", 404)

    return send_from_directory(
        os.path.dirname(file_path),
        os.path.basename(file_path),
        as_attachment=True,
        download_name=f"{track}_cyber_hygiene_report.pdf",
    )


# ---------------------------------------------------------------------------
# Campaign-level rollups (leadership-facing — admin only)
# ---------------------------------------------------------------------------

@app.route("/api/campaigns/<campaign_id>/submissions", methods=["GET"])
@_require_org_access
def list_campaign_submissions(campaign_id):
    """Participation view for the admin UI.

    No submission contents are read or returned. What differs by role is the
    respondent id: it is the bearer credential for an individual's private
    report, so leadership never receives it — they get counts, which is all a
    participation view legitimately needs.
    """
    campaign = store.get_campaign(campaign_id)
    if campaign is None:
        return _json_error("Campaign not found.", 404)

    is_operator = _role() == ROLE_OPERATOR
    submissions = {}
    counts = {}
    for track in campaign.get("tracks", []):
        respondents = store.list_respondents(campaign_id, track)
        counts[track] = len(respondents)
        if is_operator:
            submissions[track] = [
                {
                    "respondent_id": respondent_id,
                    "has_report": os.path.exists(store.report_path(campaign_id, track, respondent_id)),
                }
                for respondent_id in respondents
            ]

    body = {
        "status": "ok",
        "campaign": _public_campaign(campaign),
        "participation": counts,
        "min_aggregate_n": MIN_AGGREGATE_N,
        "role": ROLE_OPERATOR if is_operator else ROLE_VIEWER,
    }
    if is_operator:
        body["submissions"] = submissions
    return jsonify(body)


@app.route("/generateOrgReport/<campaign_id>/<mode>", methods=["POST"])
@_require_org_access
def generate_org_report_endpoint(campaign_id, mode):
    """Render a campaign-level rollup PDF.

    Org rollups expose aggregated org data and are leadership-only, hence the
    admin gate. The min-N suppression inside aggregate_assessment remains the
    second line of defense regardless of who is authenticated.
    """
    if mode not in ALLOWED_ORG_REPORT_MODES:
        return _json_error("Invalid report mode.", 400)

    try:
        output_path = store.org_report_path(campaign_id, mode)
    except InvalidInputError:
        return _json_error("Invalid request.", 400)
    except CampaignNotFoundError:
        return _json_error("Campaign not found.", 404)

    try:
        report_file, _summary = generate_org_report(mode, campaign_id, output_path)
    except LookupError:
        return _json_error("Campaign not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except RuntimeError as exc:
        return _json_error(str(exc), 500)
    except Exception:
        return _json_error("Report generation failed. Check server logs for details.", 500)

    return jsonify(
        {
            "status": "ok",
            "message": f"{os.path.basename(report_file)} is ready.",
            "mode": mode,
        }
    )


@app.route("/downloadOrgReport/<campaign_id>/<mode>", methods=["GET"])
@_require_org_access
def download_org_report(campaign_id, mode):
    if mode not in ALLOWED_ORG_REPORT_MODES:
        return _json_error("Invalid report mode.", 400)

    try:
        file_path = store.org_report_path(campaign_id, mode)
    except InvalidInputError:
        return _json_error("Invalid request.", 400)
    except CampaignNotFoundError:
        return _json_error("Campaign not found.", 404)

    if not os.path.exists(file_path):
        return _json_error("Requested report is not available yet.", 404)

    return send_from_directory(
        os.path.dirname(file_path),
        os.path.basename(file_path),
        as_attachment=True,
        download_name=f"{mode}_report.pdf",
    )


# ---------------------------------------------------------------------------
# Static front end
# ---------------------------------------------------------------------------

@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/c/<token>")
def serve_campaign_link(token):
    """The URL an employee actually opens.

    Serves the same single-page app as "/"; the browser then calls
    /api/link/<token> to discover which organization and questionnaire it is
    for. Kept deliberately short so it survives being pasted into an email,
    printed on a slide, or turned into a QR code.
    """
    return send_from_directory(app.static_folder, "index.html")


@app.route("/admin")
def serve_admin():
    """The admin console shell — deliberately not gated.

    It used to require a role, which made it unreachable in exactly the
    deployment it exists for: a browser navigating to /admin cannot attach an
    X-Admin-Token header, so with a token configured the page 403'd for
    everyone, operator included, and there was no way to reach the prompt that
    asks for the token.

    Serving it openly costs nothing. The page holds no campaign data; every
    value it displays comes from an endpoint that checks a role, and the script
    responds to the first 403 by asking for a credential. Withholding the static
    bundle was obscurity, not access control, and it broke the only way in.
    """
    return send_from_directory(app.static_folder, "admin.html")


@app.route("/<path:path>")
def serve_static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
