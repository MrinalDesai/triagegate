#!/usr/bin/env python
"""Evaluate the resolver ladder against labelled tickets.

Usage:
    python scripts/run_eval.py

Routes all 50 eval tickets from data/eval_tickets.csv and, if present,
data/ambiguous_tickets.csv.  Prints:

  - Percent of tickets resolved at each rung (svm_gate / voter_agreement / escalate)
  - Routing accuracy on the eval set (tickets that have a known domain label)
"""

from __future__ import annotations

import sys
from pathlib import Path
from collections import Counter

# Allow running as a script without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from triagegate.models.ticket import Ticket
from triagegate.pipeline.resolver import Resolver


_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_EVAL_CSV = _DATA_DIR / "eval_tickets.csv"
_AMBIGUOUS_CSV = _DATA_DIR / "ambiguous_tickets.csv"


def _route_dataframe(resolver: Resolver, df: pd.DataFrame) -> list[dict]:
    """Route every row in *df* and return a list of result dicts."""
    results = []
    for _, row in df.iterrows():
        ticket = Ticket(
            id=str(row["id"]),
            title=str(row["title"]),
            description=str(row["description"]),
        )
        result = resolver.resolve(ticket)
        entry = {
            "id": ticket.id,
            "predicted": result.domain,
            "resolved_by": result.resolved_by,
            "elapsed_ms": result.elapsed_ms,
        }
        if "domain" in df.columns:
            entry["actual"] = str(row["domain"])
        results.append(entry)
    return results


def _print_rung_breakdown(results: list[dict], label: str) -> None:
    total = len(results)
    rung_counts: Counter[str] = Counter(r["resolved_by"] for r in results)
    print(f"\n=== Rung breakdown — {label} ({total} tickets) ===")
    for rung in ("svm_gate", "voter_agreement", "escalate"):
        count = rung_counts.get(rung, 0)
        pct = 100.0 * count / total if total else 0.0
        print(f"  {rung:<20s} {count:>4d}  ({pct:5.1f}%)")


def _print_accuracy(results: list[dict], label: str) -> None:
    labelled = [r for r in results if "actual" in r]
    if not labelled:
        return
    correct = sum(
        1 for r in labelled
        if r["predicted"] == r["actual"]
    )
    total = len(labelled)
    pct = 100.0 * correct / total if total else 0.0
    print(f"\n=== Routing accuracy — {label} ===")
    print(f"  Correct: {correct}/{total}  ({pct:.1f}%)")

    # Per-rung accuracy
    by_rung: dict[str, list[dict]] = {}
    for r in labelled:
        by_rung.setdefault(r["resolved_by"], []).append(r)
    for rung in ("svm_gate", "voter_agreement", "escalate"):
        group = by_rung.get(rung, [])
        if not group:
            continue
        g_correct = sum(1 for r in group if r["predicted"] == r["actual"])
        g_pct = 100.0 * g_correct / len(group)
        print(f"    {rung:<20s} {g_correct}/{len(group)}  ({g_pct:.1f}%)")


def main() -> None:
    resolver = Resolver()
    print("Resolver ready.")

    # ----------------------------------------------------------------
    # Eval set
    # ----------------------------------------------------------------
    eval_df = pd.read_csv(_EVAL_CSV)
    eval_results = _route_dataframe(resolver, eval_df)
    _print_rung_breakdown(eval_results, "eval set")
    _print_accuracy(eval_results, "eval set")

    # ----------------------------------------------------------------
    # Ambiguous tickets (optional)
    # ----------------------------------------------------------------
    if _AMBIGUOUS_CSV.exists():
        amb_df = pd.read_csv(_AMBIGUOUS_CSV)
        amb_results = _route_dataframe(resolver, amb_df)
        _print_rung_breakdown(amb_results, "ambiguous tickets")
        _print_accuracy(amb_results, "ambiguous tickets")
    else:
        print(f"\n(No ambiguous tickets file found at {_AMBIGUOUS_CSV})")

    print()


if __name__ == "__main__":
    main()
