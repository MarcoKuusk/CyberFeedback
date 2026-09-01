"""Export an anonymized research dataset from stored campaign data.

Produces four CSVs suitable for analysis and for publication alongside a thesis:

    campaigns.csv             one row per campaign
    respondents.csv           one row per respondent
    respondent_categories.csv one row per respondent x category
    responses_long.csv        one row per respondent x question

Pseudonymization is the point of this script, not a side effect:

* Organizations become `org_1`, `org_2`, ... in stable creation order. The real
  name never appears, so the dataset can be shared without naming a client.
* Respondents become `org_1_employee_001`. The stored `respondent_id` is
  deliberately excluded: it is the bearer credential that downloads that
  person's private report, so a dataset containing it would hand every reader
  the ability to open individual reports.
* Only the responses themselves are exported. Submission metadata is dropped
  wholesale rather than filtered, so a field added there later cannot silently
  start leaking into published data.

Usage:
    python scripts/export_research_data.py --out research_export
    python scripts/export_research_data.py --out research_export --include-open
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import campaign_store as store  # noqa: E402
from utils.report_analysis import analyze_assessment  # noqa: E402


def _org_pseudonyms(campaigns: List[Dict[str, Any]]) -> Dict[str, str]:
    """Map each distinct org slug to org_N, ordered by first appearance.

    Keyed by slug rather than campaign so an organization assessed twice keeps
    one pseudonym across both campaigns — which is what makes longitudinal
    comparison possible without re-identifying anyone.
    """
    pseudonyms: Dict[str, str] = {}
    for campaign in campaigns:
        slug = campaign.get("org_slug", "unknown")
        if slug not in pseudonyms:
            pseudonyms[slug] = f"org_{len(pseudonyms) + 1}"
    return pseudonyms


def _write(path: str, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    # newline="" per the csv module contract; without it Windows writes \r\r\n.
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {os.path.basename(path)}: {len(rows)} rows")


def collect(include_open: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    campaigns = sorted(store.list_campaigns(), key=lambda c: c.get("created_at", ""))
    pseudonyms = _org_pseudonyms(campaigns)

    campaign_rows: List[Dict[str, Any]] = []
    respondent_rows: List[Dict[str, Any]] = []
    category_rows: List[Dict[str, Any]] = []
    response_rows: List[Dict[str, Any]] = []

    for index, campaign in enumerate(campaigns, start=1):
        campaign_id = campaign["campaign_id"]
        org_ref = pseudonyms[campaign.get("org_slug", "unknown")]
        campaign_ref = f"campaign_{index}"

        # An open campaign is still collecting; exporting mid-collection
        # produces a dataset that silently disagrees with the final one.
        if campaign.get("status") == "open" and not include_open:
            print(f"  skipping {campaign_ref} ({org_ref}) — still open; use --include-open to override")
            continue

        counts: Dict[str, int] = {}
        for track in campaign.get("tracks", []):
            respondent_ids = store.list_respondents(campaign_id, track)
            counts[track] = len(respondent_ids)

            for position, respondent_id in enumerate(sorted(respondent_ids), start=1):
                record = store.load_record(campaign_id, track, respondent_id)
                responses = record.get("responses", [])
                # Pseudonym is positional within (campaign, track) and never
                # derived from the real id, so it cannot be reversed.
                respondent_ref = f"{org_ref}_{track}_{position:03d}"

                summary = analyze_assessment(responses, track)
                consent = record.get("consent", {})

                respondent_rows.append(
                    {
                        "org_ref": org_ref,
                        "campaign_ref": campaign_ref,
                        "track": track,
                        "respondent_ref": respondent_ref,
                        "locale": record.get("locale", ""),
                        "submitted_at": record.get("submitted_at", ""),
                        "consent_version": consent.get("version", ""),
                        "consent_recorded_at": consent.get("recorded_at", ""),
                        "questions_answered": len(summary.get("question_summaries", [])),
                        "overall_score": summary.get("overall_score", 0.0),
                        "maturity_band": summary.get("maturity_label", ""),
                    }
                )

                for category, score in sorted(summary.get("category_scores", {}).items()):
                    category_rows.append(
                        {
                            "org_ref": org_ref,
                            "campaign_ref": campaign_ref,
                            "track": track,
                            "respondent_ref": respondent_ref,
                            "category": category,
                            "score": score,
                        }
                    )

                for item in summary.get("question_summaries", []):
                    max_score = item.get("max_score", 0)
                    response_rows.append(
                        {
                            "org_ref": org_ref,
                            "campaign_ref": campaign_ref,
                            "track": track,
                            "respondent_ref": respondent_ref,
                            "category": item.get("category", ""),
                            "question": item.get("question", ""),
                            "selected_answer": item.get("selected_answer", ""),
                            "score": item.get("score", 0),
                            "max_score": max_score,
                            "ratio": round(item.get("score", 0) / max_score, 4) if max_score else "",
                        }
                    )

        campaign_rows.append(
            {
                "org_ref": org_ref,
                "campaign_ref": campaign_ref,
                "locale": campaign.get("locale", ""),
                "status": campaign.get("status", ""),
                "created_at": campaign.get("created_at", ""),
                "tracks": "|".join(campaign.get("tracks", [])),
                "employee_n": counts.get("employee", 0),
                "organization_n": counts.get("organization", 0),
            }
        )

    return {
        "campaigns": campaign_rows,
        "respondents": respondent_rows,
        "respondent_categories": category_rows,
        "responses_long": response_rows,
    }


FIELDS = {
    "campaigns": [
        "org_ref", "campaign_ref", "locale", "status", "created_at",
        "tracks", "employee_n", "organization_n",
    ],
    "respondents": [
        "org_ref", "campaign_ref", "track", "respondent_ref", "locale",
        "submitted_at", "consent_version", "consent_recorded_at",
        "questions_answered", "overall_score", "maturity_band",
    ],
    "respondent_categories": [
        "org_ref", "campaign_ref", "track", "respondent_ref", "category", "score",
    ],
    "responses_long": [
        "org_ref", "campaign_ref", "track", "respondent_ref", "category",
        "question", "selected_answer", "score", "max_score", "ratio",
    ],
}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export an anonymized research dataset.")
    parser.add_argument("--out", required=True, help="Output directory for the CSV files.")
    parser.add_argument(
        "--include-open",
        action="store_true",
        help="Also export campaigns still accepting responses (default: skip them).",
    )
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    print(f"Exporting to {os.path.abspath(args.out)}")

    tables = collect(include_open=args.include_open)
    for name, rows in tables.items():
        _write(os.path.join(args.out, f"{name}.csv"), FIELDS[name], rows)

    if not tables["respondents"]:
        print("\nNo respondents exported. Closed campaigns only are exported unless --include-open is given.")
    else:
        print(f"\nDone. {len(tables['respondents'])} respondents across {len(tables['campaigns'])} campaigns.")
        print("No organization name, respondent id, or submission metadata is present in these files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
