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

def _admin_ok() -> bool:
    """Guard campaign management.

    PHASE1_PLAN flagged unauthenticated campaign creation as acceptable only
    while the app binds 127.0.0.1. The pilot binds to the org's LAN, at which
    point every employee could reach it, so the gate lands now: a token if
    CYBERFEEDBACK_ADMIN_TOKEN is set, loopback-only otherwise.
    """
    token = os.getenv("CYBERFEEDBACK_ADMIN_TOKEN", "").strip()
    if token:
        return hmac.compare_digest(request.headers.get("X-Admin-Token", ""), token)
    return request.remote_addr in LOOPBACK_ADDRESSES


def _require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _admin_ok():
            return _json_error("Not authorized.", 403)
        return view(*args, **kwargs)

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

    return jsonify({"status": "ok", "campaign": _public_campaign(campaign)}), 201


@app.route("/api/campaigns", methods=["GET"])
@_require_admin
def list_campaigns():
    campaigns = store.list_campaigns()
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
        }
    )


@app.route("/api/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    """Public: a respondent holding the link resolves which tracks are open."""
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

@app.route("/saveAssessmentData/<campaign_id>/<track>", methods=["POST"])
def save_assessment_data(campaign_id, track):
    if track not in ALLOWED_TRACKS:
        return _json_error("Invalid report type.", 400)

    payload = request.get_json(silent=True)
    is_valid, error_message = _validate_payload(payload)
    if not is_valid:
        return _json_error(error_message, 400)

    try:
        respondent_id = store.save_submission(campaign_id, track, payload)
    except InvalidInputError:
        return _json_error("Assessment could not be saved.", 400)
    except CampaignNotFoundError:
        return _json_error("Campaign or track not found.", 404)

    return jsonify(
        {
            "status": "ok",
            "message": f"{track.title()} assessment saved.",
            "respondent_id": respondent_id,
        }
    )


@app.route("/generateFeedback/<campaign_id>/<track>/<respondent_id>", methods=["POST"])
def generate_feedback(campaign_id, track, respondent_id):
    if track not in ALLOWED_TRACKS:
        return _json_error("Invalid report type.", 400)

    try:
        assessment_data, metadata = store.load_submission(campaign_id, track, respondent_id)
        output_path = store.report_path(campaign_id, track, respondent_id)
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
        return _json_error("Report generation failed. Check server logs for details.", 500)

    return jsonify({"status": "ok", "message": "Your report is ready.", "summary": summary})


@app.route("/downloadReport/<campaign_id>/<track>/<respondent_id>", methods=["GET"])
def download_report(campaign_id, track, respondent_id):
    if track not in ALLOWED_TRACKS:
        return _json_error("Invalid report type.", 400)

    try:
        file_path = store.report_path(campaign_id, track, respondent_id)
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
@_require_admin
def list_campaign_submissions(campaign_id):
    """Participation view for the admin UI.

    No submission contents are read or returned — only opaque respondent ids and
    whether a PDF exists. `min_aggregate_n` lets the UI explain why an aggregate
    is unavailable for a small track without exposing per-respondent data.
    """
    campaign = store.get_campaign(campaign_id)
    if campaign is None:
        return _json_error("Campaign not found.", 404)

    submissions = {}
    for track in campaign.get("tracks", []):
        rows = []
        for respondent_id in store.list_respondents(campaign_id, track):
            has_report = os.path.exists(store.report_path(campaign_id, track, respondent_id))
            rows.append({"respondent_id": respondent_id, "has_report": has_report})
        submissions[track] = rows

    return jsonify(
        {
            "status": "ok",
            "campaign": _public_campaign(campaign),
            "submissions": submissions,
            "min_aggregate_n": MIN_AGGREGATE_N,
        }
    )


@app.route("/generateOrgReport/<campaign_id>/<mode>", methods=["POST"])
@_require_admin
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
@_require_admin
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


@app.route("/admin")
@_require_admin
def serve_admin():
    """Campaign admin UI. Gated by the same token/loopback rule as the API it
    drives — the pilot binds to the org LAN, so this must not be world-readable."""
    return send_from_directory(app.static_folder, "admin.html")


@app.route("/<path:path>")
def serve_static_files(path):
    # The admin bundle is served only through the gated /admin route; otherwise
    # the catch-all would hand out admin.html / admin.js to anyone on the LAN and
    # quietly undo the gate.
    if os.path.basename(path).lower().startswith("admin.") and not _admin_ok():
        return _json_error("Not authorized.", 403)
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
