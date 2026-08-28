#!/usr/bin/env python3
"""Helper script — post an EscalationReport JSON file to the TriageGate API.

Usage:
    python scripts/save_escalation.py <report.json> [--url http://localhost:8000]

The JSON file must match the EscalationReport schema.  The ticket_id is read
from the file and used in the URL path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("httpx is required: pip install httpx", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Post an EscalationReport to TriageGate.")
    parser.add_argument("report_file", help="Path to a JSON file containing the EscalationReport.")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the TriageGate server (default: http://localhost:8000).",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.report_file).read_text(encoding="utf-8"))
    ticket_id = data.get("ticket_id")
    if not ticket_id:
        print("ERROR: report JSON must contain a 'ticket_id' field.", file=sys.stderr)
        sys.exit(1)

    endpoint = f"{args.url.rstrip('/')}/api/escalations/{ticket_id}/report"
    print(f"POST {endpoint}")

    response = httpx.post(endpoint, json=data, timeout=30)
    response.raise_for_status()
    print(f"Saved — HTTP {response.status_code}")
    print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    main()
