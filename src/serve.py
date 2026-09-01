"""Production entry point.

`python src/server.py` starts Flask's development server bound to loopback:
fine for building, unusable for a real engagement and explicitly not for
production. This module serves the same app under waitress, with the
configuration checks that a deployment actually needs made *before* the socket
opens rather than discovered by a client.

    python src/serve.py                      # loopback, development
    python src/serve.py --host 0.0.0.0       # reachable deployment

Environment:
    OPENAI_API_KEY               required — report generation fails without it
    CYBERFEEDBACK_ADMIN_TOKEN    required when binding beyond loopback (operator)
    CYBERFEEDBACK_PUBLIC_URL     public base URL, used to build campaign links
    CYBERFEEDBACK_HOST / _PORT / _THREADS

Leadership credentials are not configured here: each campaign mints its own
viewer token, scoped to that campaign, when it is created.
"""

from __future__ import annotations

import argparse
import os
import sys

from waitress import serve

from server import app

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Report generation is synchronous and can take tens of seconds, so a thread is
# occupied for the whole call. Waitress's default of 4 would let five people
# generating reports stall everyone still answering questions.
DEFAULT_THREADS = 16


def _env_int(name: str, fallback: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve CyberFeedback with a production WSGI server.")
    parser.add_argument("--host", default=os.getenv("CYBERFEEDBACK_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=_env_int("CYBERFEEDBACK_PORT", 8080))
    parser.add_argument("--threads", type=int, default=_env_int("CYBERFEEDBACK_THREADS", DEFAULT_THREADS))
    return parser.parse_args(argv)


def preflight(host: str) -> list[str]:
    """Configuration errors that must stop the server from starting.

    Each of these is something that would otherwise surface mid-engagement, in
    front of the client, as an unexplained failure.
    """
    problems: list[str] = []
    exposed = host not in LOOPBACK_HOSTS

    if not os.getenv("OPENAI_API_KEY", "").strip():
        problems.append(
            "OPENAI_API_KEY is not set. Every report would fail at the point a respondent asks for it."
        )

    if exposed and not os.getenv("CYBERFEEDBACK_ADMIN_TOKEN", "").strip():
        # Without it, _role() falls back to trusting loopback. That is not
        # insecure, but it locks you out of your own admin UI from anywhere but
        # the server console — a failure discovered at the worst moment.
        problems.append(
            "CYBERFEEDBACK_ADMIN_TOKEN is required when binding beyond loopback. "
            "Without it the admin interface is reachable only from the server itself."
        )

    if exposed and not os.getenv("CYBERFEEDBACK_PUBLIC_URL", "").strip():
        problems.append(
            "CYBERFEEDBACK_PUBLIC_URL is not set. Campaign links would be built from the "
            "request host, which behind a reverse proxy is often wrong (http:// or an "
            "internal name) and produces links that do not work for staff."
        )

    return problems


def warnings_for(host: str) -> list[str]:
    """Worth saying out loud, but not worth refusing to start over."""
    notes: list[str] = []
    public_url = os.getenv("CYBERFEEDBACK_PUBLIC_URL", "").strip()

    if host not in LOOPBACK_HOSTS and public_url.startswith("http://"):
        notes.append(
            "CYBERFEEDBACK_PUBLIC_URL is http://. Assessment responses and campaign links "
            "would travel in clear text. Terminate HTTPS at a reverse proxy before inviting a client."
        )

    if os.getenv("CYBERFEEDBACK_VIEWER_TOKEN", "").strip():
        # It used to be a global role token. Leaving it set is harmless but
        # misleading: it grants nothing, and someone will assume it does.
        notes.append(
            "CYBERFEEDBACK_VIEWER_TOKEN is set but no longer used. Leadership access is now a "
            "per-campaign viewer token issued when the campaign is created. Unset it."
        )

    return notes


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    problems = preflight(args.host)
    if problems:
        print("Refusing to start:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\nSee docs/DEPLOYMENT.md.", file=sys.stderr)
        return 1

    for note in warnings_for(args.host):
        print(f"warning: {note}", file=sys.stderr)

    public_url = os.getenv("CYBERFEEDBACK_PUBLIC_URL", "").strip() or f"http://{args.host}:{args.port}"
    print(f"CyberFeedback listening on {args.host}:{args.port} ({args.threads} threads)")
    print(f"Campaign links will be issued as {public_url.rstrip('/')}/c/<token>")
    print(f"Admin UI: {public_url.rstrip('/')}/admin")

    serve(app, host=args.host, port=args.port, threads=args.threads)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
