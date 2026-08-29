#!/usr/bin/env python3
"""Wait for a pending escalation to be approved or rejected.

Usage:
    python scripts/wait_for_approval.py TICKET_ID [--url URL] [--timeout SECONDS] [--interval SECONDS]

Exit codes:
    0 — approved
    1 — timeout (no decision within --timeout seconds)
    2 — rejected
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    import httpx
except ImportError:
    print("httpx is required: pip install httpx", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poll GET /api/escalations/{id} until approved or rejected."
    )
    parser.add_argument("ticket_id", help="Ticket ID to poll for approval.")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the TriageGate server (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="Maximum seconds to wait for a decision (default: 900).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Polling interval in seconds (default: 10).",
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    endpoint = f"{base_url}/api/escalations/{args.ticket_id}"
    deadline = time.monotonic() + args.timeout
    last_status: str | None = None

    print(f"Polling {endpoint} (timeout={args.timeout}s, interval={args.interval}s)")

    while True:
        try:
            resp = httpx.get(endpoint, timeout=10)
        except Exception as exc:
            print(f"  [warn] Request failed: {exc}", file=sys.stderr)
        else:
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status")

                if status != last_status:
                    print(f"  status → {status}")
                    last_status = status

                if status == "approved":
                    print("APPROVED — proceeding with patch.")
                    sys.exit(0)
                elif status == "rejected":
                    print("REJECTED — patch not applied.")
                    sys.exit(2)
                # Any other status (pending_approval, completed, …): keep polling
            elif resp.status_code == 404:
                print(f"  [info] No report yet for {args.ticket_id!r} — still waiting…")
            else:
                print(f"  [warn] Unexpected HTTP {resp.status_code}", file=sys.stderr)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                f"TIMEOUT — no decision received within {args.timeout}s.",
                file=sys.stderr,
            )
            sys.exit(1)

        sleep_for = min(args.interval, remaining)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
