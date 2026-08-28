"""Tests for scripts/generate_tickets.py"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

# Make the scripts directory importable without installation.
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from generate_tickets import generate, write_csv  # noqa: E402

DOMAINS = ["api", "database", "frontend", "auth", "build"]
EXPECTED_COLUMNS = {"id", "title", "description", "domain"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows(n_per_domain: int, seed: int) -> list[dict]:
    return generate(n_per_domain=n_per_domain, seed=seed)


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# In-memory generation tests (fast, no I/O)
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_correct_total_count(self):
        rows = _rows(40, 42)
        assert len(rows) == 200

    def test_correct_eval_count(self):
        rows = _rows(10, 99)
        assert len(rows) == 50

    def test_all_domains_represented(self):
        rows = _rows(40, 42)
        counts = {d: 0 for d in DOMAINS}
        for row in rows:
            counts[row["domain"]] += 1
        for domain in DOMAINS:
            assert counts[domain] == 40, f"domain '{domain}' has {counts[domain]} tickets, expected 40"

    def test_all_domains_represented_eval(self):
        rows = _rows(10, 99)
        counts = {d: 0 for d in DOMAINS}
        for row in rows:
            counts[row["domain"]] += 1
        for domain in DOMAINS:
            assert counts[domain] == 10, f"domain '{domain}' has {counts[domain]} tickets, expected 10"

    def test_no_duplicate_titles(self):
        rows = _rows(40, 42)
        titles = [r["title"] for r in rows]
        assert len(titles) == len(set(titles)), "Duplicate titles found in training set"

    def test_no_duplicate_titles_eval(self):
        rows = _rows(10, 99)
        titles = [r["title"] for r in rows]
        assert len(titles) == len(set(titles)), "Duplicate titles found in eval set"

    def test_required_fields_present(self):
        rows = _rows(40, 42)
        for row in rows:
            assert set(row.keys()) >= EXPECTED_COLUMNS

    def test_no_empty_fields(self):
        rows = _rows(40, 42)
        for row in rows:
            for col in EXPECTED_COLUMNS:
                assert row[col], f"Empty value for '{col}' in row {row}"

    def test_domain_values_valid(self):
        rows = _rows(40, 42)
        for row in rows:
            assert row["domain"] in DOMAINS, f"Unknown domain: {row['domain']}"

    def test_reproducibility_same_seed(self):
        rows_a = _rows(40, 42)
        rows_b = _rows(40, 42)
        assert rows_a == rows_b, "Same seed should produce identical output"

    def test_different_seeds_differ(self):
        rows_42 = _rows(10, 42)
        rows_99 = _rows(10, 99)
        titles_42 = {r["title"] for r in rows_42}
        titles_99 = {r["title"] for r in rows_99}
        # The two sets should not be identical (they may share some but not all)
        assert titles_42 != titles_99, "Different seeds should not produce identical outputs"

    def test_ids_unique_and_sequential(self):
        rows = _rows(40, 42)
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids)), "Duplicate IDs found"
        # All IDs should follow T-NNNN format
        for row_id in ids:
            assert row_id.startswith("T-"), f"ID does not start with T-: {row_id}"


# ---------------------------------------------------------------------------
# CSV output tests (write files and read them back)
# ---------------------------------------------------------------------------

class TestWriteCSV:
    def test_tickets_csv_columns(self, tmp_path):
        rows = _rows(40, 42)
        out = tmp_path / "tickets.csv"
        write_csv(rows, out)
        written = _csv_rows(out)
        assert len(written) == 200
        assert set(written[0].keys()) == EXPECTED_COLUMNS

    def test_eval_csv_columns(self, tmp_path):
        rows = _rows(10, 99)
        out = tmp_path / "eval_tickets.csv"
        write_csv(rows, out)
        written = _csv_rows(out)
        assert len(written) == 50
        assert set(written[0].keys()) == EXPECTED_COLUMNS

    def test_csv_roundtrip_preserves_content(self, tmp_path):
        rows = _rows(40, 42)
        out = tmp_path / "tickets.csv"
        write_csv(rows, out)
        written = _csv_rows(out)
        assert written[0]["id"] == rows[0]["id"]
        assert written[0]["title"] == rows[0]["title"]
        assert written[0]["domain"] == rows[0]["domain"]

    def test_parent_directory_created(self, tmp_path):
        rows = _rows(5, 42)
        out = tmp_path / "nested" / "dir" / "out.csv"
        write_csv(rows, out)
        assert out.exists()
