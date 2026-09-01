"""Regenerate PDFs for a campaign after a failed batch.

The realistic failure during an engagement is not one bad report — it is a
whole session's worth failing for one shared reason: the API key was not set,
the model name was wrong, or the upstream API had an outage while thirty people
were answering. Their submissions are safely stored either way; only the PDFs
are missing. This rebuilds them without asking anyone to answer twice.

Runs on the server, as the operator. It never reads a report out to anyone: it
writes each PDF back to the path that respondent's own link already serves.

Usage:
    python scripts/regenerate_reports.py --campaign <campaign_id> --missing-only
    python scripts/regenerate_reports.py --campaign <campaign_id> --all
    python scripts/regenerate_reports.py --campaign <campaign_id> --org-reports
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import campaign_store as store  # noqa: E402
from main import generate_org_report, generate_report  # noqa: E402


def regenerate_individual(campaign_id: str, missing_only: bool) -> int:
    campaign = store.get_campaign(campaign_id)
    if campaign is None:
        print(f"Unknown campaign: {campaign_id}")
        return 1

    attempted = succeeded = skipped = 0
    for track in campaign.get("tracks", []):
        for respondent_id in store.list_respondents(campaign_id, track):
            output_path = store.report_path(campaign_id, track, respondent_id)
            if missing_only and os.path.exists(output_path):
                skipped += 1
                continue

            attempted += 1
            try:
                assessment, metadata = store.load_submission(campaign_id, track, respondent_id)
                generate_report(track, assessment, metadata, output_path)
                succeeded += 1
                print(f"  ok   {track}/{respondent_id}")
            except Exception as exc:  # noqa: BLE001 - one failure must not stop the batch
                # The respondent id is an opaque uuid, not personal data, and
                # printing it is what makes a partial failure actionable.
                print(f"  FAIL {track}/{respondent_id}: {type(exc).__name__}: {exc}")

    print(f"\n{succeeded}/{attempted} regenerated, {skipped} already present.")
    return 0 if succeeded == attempted else 2


def regenerate_org(campaign_id: str, modes: List[str]) -> int:
    failures = 0
    for mode in modes:
        try:
            output_path = store.org_report_path(campaign_id, mode)
            generate_org_report(mode, campaign_id, output_path)
            print(f"  ok   {mode}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL {mode}: {type(exc).__name__}: {exc}")
    return 0 if failures == 0 else 2


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate report PDFs for a campaign.")
    parser.add_argument("--campaign", required=True, help="Campaign id.")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--missing-only", action="store_true", help="Only respondents with no PDF (default).")
    scope.add_argument("--all", action="store_true", help="Rebuild every individual report.")
    parser.add_argument("--org-reports", action="store_true", help="Also rebuild the campaign rollups.")
    args = parser.parse_args(argv)

    if not os.getenv("OPENAI_API_KEY", "").strip():
        print("OPENAI_API_KEY is not set — that is very likely why the batch failed in the first place.")
        return 1

    print(f"Campaign {args.campaign}")
    status = regenerate_individual(args.campaign, missing_only=not args.all)

    if args.org_reports:
        campaign = store.get_campaign(args.campaign)
        tracks = campaign.get("tracks", []) if campaign else []
        modes = []
        if "employee" in tracks:
            modes.append("aggregate")
        if "organization" in tracks:
            modes.append("organization")
        if "employee" in tracks and "organization" in tracks:
            modes.append("combined")

        print("\nOrganization reports")
        status = regenerate_org(args.campaign, modes) or status

    return status


if __name__ == "__main__":
    raise SystemExit(main())
