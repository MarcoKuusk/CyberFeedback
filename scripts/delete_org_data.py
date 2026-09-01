"""Erase every trace of one organization.

This exists so the retention promise made to a client is something you can
actually perform, on request, in front of them — not a paragraph in a policy
document. It removes, for the chosen organization:

  * every stored submission            src/data/<org_slug>/...
  * every generated PDF                src/Generated_PDF_Report/<org_slug>/...
  * every campaign registry entry, including the link tokens

Deletion is irreversible and there is no undo. The script therefore lists
exactly what it will remove and requires the organization slug to be retyped
before anything is touched.

Usage:
    python scripts/delete_org_data.py --list
    python scripts/delete_org_data.py --org acme-ltd
    python scripts/delete_org_data.py --org acme-ltd --yes    # non-interactive
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import campaign_store as store  # noqa: E402


def _org_directories(org_slug: str) -> List[str]:
    """Both roots for this org, resolved through the store's containment guard.

    Reusing `_safe_join` means a hand-typed slug cannot walk out of the data
    directory and delete something else — the argument is user input, and this
    operation is destructive.
    """
    directories = []
    for base in (store.DATA_DIR, store.REPORT_DIR):
        try:
            candidate = store._safe_join(base, org_slug)
        except store.InvalidInputError:
            continue
        if os.path.isdir(candidate):
            directories.append(candidate)
    return directories


def summarize(org_slug: str) -> Dict[str, Any]:
    campaigns = [c for c in store.list_campaigns() if c.get("org_slug") == org_slug]
    directories = _org_directories(org_slug)

    submissions = 0
    pdfs = 0
    for directory in directories:
        for _root, _dirs, files in os.walk(directory):
            submissions += sum(1 for f in files if f.endswith(".json"))
            pdfs += sum(1 for f in files if f.endswith(".pdf"))

    return {
        "org_slug": org_slug,
        "org_names": sorted({c.get("org_name", "") for c in campaigns}),
        "campaigns": campaigns,
        "directories": directories,
        "submissions": submissions,
        "pdfs": pdfs,
    }


def delete(org_slug: str) -> Dict[str, int]:
    """Remove files first, then the registry entries.

    In that order because the registry is what maps a campaign to its files: if
    the run dies midway, an orphaned registry entry is discoverable and can be
    cleaned up, whereas orphaned files under a slug nothing references are not.
    """
    removed_dirs = 0
    for directory in _org_directories(org_slug):
        shutil.rmtree(directory)
        removed_dirs += 1

    registry = store._read_registry()
    doomed = [cid for cid, c in registry["campaigns"].items() if c.get("org_slug") == org_slug]
    for campaign_id in doomed:
        del registry["campaigns"][campaign_id]
    if doomed:
        store._write_registry(registry)

    return {"directories": removed_dirs, "campaigns": len(doomed)}


def _list_orgs() -> int:
    campaigns = store.list_campaigns()
    if not campaigns:
        print("No campaigns on record.")
        return 0

    by_slug: Dict[str, List[Dict[str, Any]]] = {}
    for campaign in campaigns:
        by_slug.setdefault(campaign.get("org_slug", "unknown"), []).append(campaign)

    print(f"{'slug':<28} {'name':<32} campaigns")
    for slug in sorted(by_slug):
        name = by_slug[slug][0].get("org_name", "")
        print(f"{slug:<28} {name:<32} {len(by_slug[slug])}")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Permanently delete one organization's data.")
    parser.add_argument("--org", help="Organization slug (see --list).")
    parser.add_argument("--list", action="store_true", help="List known organizations and exit.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args(argv)

    if args.list:
        return _list_orgs()
    if not args.org:
        parser.error("either --org or --list is required")

    report = summarize(args.org)
    if not report["campaigns"] and not report["directories"]:
        print(f"Nothing found for '{args.org}'. Run --list to see known organizations.")
        return 1

    print(f"About to permanently delete data for: {args.org}")
    for name in report["org_names"]:
        print(f"  organization name : {name}")
    print(f"  campaigns         : {len(report['campaigns'])}")
    print(f"  submissions       : {report['submissions']}")
    print(f"  generated PDFs    : {report['pdfs']}")
    for directory in report["directories"]:
        print(f"  directory         : {directory}")
    print("\nThis cannot be undone.")

    if not args.yes:
        typed = input(f"Retype the slug '{args.org}' to confirm: ").strip()
        if typed != args.org:
            print("Confirmation did not match. Nothing was deleted.")
            return 1

    result = delete(args.org)
    print(f"\nDeleted {result['directories']} directories and {result['campaigns']} campaign records.")
    print("Any link tokens for this organization are now dead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
