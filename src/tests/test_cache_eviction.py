"""Unit tests for CacheEvictor — LRU / age / count eviction.

Run:
    python src/tests/test_cache_eviction.py
    python -m pytest src/tests/test_cache_eviction.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from netos_build.cache_eviction import CacheEvictor, evict_from_env
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)


def _ts(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).isoformat()


def _make_cache_dir(tmp: str, entries: list[dict]) -> Path:
    """Create a fake cache directory with archives and an index.json.

    Each entry dict: {key, size_bytes, days_ago}
    """
    d = Path(tmp) / "cache"
    d.mkdir(parents=True)
    index: dict = {}
    for e in entries:
        key  = e["key"]
        size = e.get("size_bytes", 1024)
        days = e.get("days_ago", 0.0)
        fname = f"{key}.tar.gz"
        (d / fname).write_bytes(b"x" * min(size, 1024))   # tiny files for speed
        # Real stat size will differ; patch size via index
        index[key] = {
            "arch": "arm64",
            "buildroot_version": "2026.02.1",
            "size_bytes": size,
            "packed_at": _ts(days),
        }
    (d / "index.json").write_text(json.dumps(index))
    return d


# ---------------------------------------------------------------------------
# No policy — nothing evicted
# ---------------------------------------------------------------------------

class TestNoPolicies(unittest.TestCase):

    def test_no_policy_evicts_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "arm64-br2026.02.1-aabbccdd", "size_bytes": 500 * 1024**2, "days_ago": 90},
            ])
            ev = CacheEvictor(d)
            deleted = ev.evict()
            self.assertEqual(deleted, [])

    def test_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "empty"
            d.mkdir()
            ev = CacheEvictor(d, max_entries=1)
            deleted = ev.evict()
            self.assertEqual(deleted, [])

    def test_nonexistent_dir_returns_empty(self):
        ev = CacheEvictor(Path("/nonexistent/cache/dir"), max_entries=1)
        self.assertEqual(ev.evict(), [])


# ---------------------------------------------------------------------------
# max_age_days policy
# ---------------------------------------------------------------------------

class TestAgePolicy(unittest.TestCase):

    def test_old_entry_evicted(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "old", "days_ago": 31},
                {"key": "new", "days_ago": 1},
            ])
            ev = CacheEvictor(d, max_age_days=30)
            with patch("netos_build.cache_eviction.datetime") as mock_dt:
                mock_dt.now.return_value = _NOW
                mock_dt.fromisoformat = datetime.fromisoformat
                deleted = ev.evict()
            names = [p.name for p in deleted]
            self.assertIn("old.tar.gz", names)
            self.assertNotIn("new.tar.gz", names)

    def test_entry_exactly_at_boundary_not_evicted(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "borderline", "days_ago": 30},   # exactly 30 days → keep
            ])
            ev = CacheEvictor(d, max_age_days=30)
            with patch("netos_build.cache_eviction.datetime") as mock_dt:
                mock_dt.now.return_value = _NOW
                mock_dt.fromisoformat = datetime.fromisoformat
                deleted = ev.evict()
            self.assertEqual(deleted, [])

    def test_all_old_entries_evicted(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "a", "days_ago": 60},
                {"key": "b", "days_ago": 45},
                {"key": "c", "days_ago": 31},
            ])
            ev = CacheEvictor(d, max_age_days=30)
            with patch("netos_build.cache_eviction.datetime") as mock_dt:
                mock_dt.now.return_value = _NOW
                mock_dt.fromisoformat = datetime.fromisoformat
                deleted = ev.evict()
            self.assertEqual(len(deleted), 3)

    def test_file_deleted_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "old", "days_ago": 40},
            ])
            ev = CacheEvictor(d, max_age_days=30)
            with patch("netos_build.cache_eviction.datetime") as mock_dt:
                mock_dt.now.return_value = _NOW
                mock_dt.fromisoformat = datetime.fromisoformat
                ev.evict()
            self.assertFalse((d / "old.tar.gz").exists())


# ---------------------------------------------------------------------------
# max_size_mb policy
# ---------------------------------------------------------------------------

class TestSizePolicy(unittest.TestCase):

    def test_evicts_oldest_when_over_limit(self):
        """3 entries × 200 MB (SI) = 600 MB; limit 400 MB → evict 1 oldest."""
        MB = 1_000_000  # SI megabyte — matches size_mb = size_bytes / 1e6
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "old",    "size_bytes": 200 * MB, "days_ago": 10},
                {"key": "middle", "size_bytes": 200 * MB, "days_ago": 5},
                {"key": "new",    "size_bytes": 200 * MB, "days_ago": 1},
            ])
            ev = CacheEvictor(d, max_size_mb=400)
            deleted = ev.evict()
            self.assertEqual(len(deleted), 1)
            self.assertIn("old.tar.gz", [p.name for p in deleted])

    def test_no_eviction_when_under_limit(self):
        MB = 1_000_000
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "a", "size_bytes": 100 * MB, "days_ago": 5},
                {"key": "b", "size_bytes": 100 * MB, "days_ago": 1},
            ])
            ev = CacheEvictor(d, max_size_mb=500)
            deleted = ev.evict()
            self.assertEqual(deleted, [])

    def test_evicts_multiple_oldest_to_fit(self):
        """5 × 200 MB (SI) = 1000 MB; limit 300 MB → evict 4, keep 1 newest."""
        MB = 1_000_000
        entries = [
            {"key": f"e{i}", "size_bytes": 200 * MB, "days_ago": 10 - i}
            for i in range(5)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, entries)
            ev = CacheEvictor(d, max_size_mb=300)
            deleted = ev.evict()
            self.assertEqual(len(deleted), 4)
            # Newest entry (days_ago=6, key=e4) must survive
            self.assertTrue((d / "e4.tar.gz").exists())


# ---------------------------------------------------------------------------
# max_entries policy
# ---------------------------------------------------------------------------

class TestCountPolicy(unittest.TestCase):

    def test_evicts_oldest_when_over_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "oldest", "days_ago": 10},
                {"key": "middle", "days_ago": 5},
                {"key": "newest", "days_ago": 1},
            ])
            ev = CacheEvictor(d, max_entries=2)
            deleted = ev.evict()
            self.assertEqual(len(deleted), 1)
            self.assertIn("oldest.tar.gz", [p.name for p in deleted])

    def test_no_eviction_at_exact_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "a", "days_ago": 5},
                {"key": "b", "days_ago": 1},
            ])
            ev = CacheEvictor(d, max_entries=2)
            deleted = ev.evict()
            self.assertEqual(deleted, [])

    def test_evicts_down_to_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = [{"key": f"k{i}", "days_ago": 10 - i} for i in range(5)]
            d = _make_cache_dir(tmp, entries)
            ev = CacheEvictor(d, max_entries=2)
            deleted = ev.evict()
            self.assertEqual(len(deleted), 3)
            # k3 and k4 (newest) must survive
            self.assertTrue((d / "k3.tar.gz").exists())
            self.assertTrue((d / "k4.tar.gz").exists())

    def test_max_entries_one_keeps_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "old",    "days_ago": 5},
                {"key": "newer",  "days_ago": 2},
                {"key": "newest", "days_ago": 0.1},
            ])
            ev = CacheEvictor(d, max_entries=1)
            deleted = ev.evict()
            self.assertEqual(len(deleted), 2)
            self.assertTrue((d / "newest.tar.gz").exists())


# ---------------------------------------------------------------------------
# Combined policies
# ---------------------------------------------------------------------------

class TestCombinedPolicies(unittest.TestCase):

    def test_age_and_count_combined(self):
        """Age evicts old entries; count evicts excess recent ones."""
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "ancient", "days_ago": 40},   # age-evicted
                {"key": "old",     "days_ago": 10},
                {"key": "mid",     "days_ago": 5},
                {"key": "new",     "days_ago": 1},
            ])
            ev = CacheEvictor(d, max_age_days=30, max_entries=2)
            with patch("netos_build.cache_eviction.datetime") as mock_dt:
                mock_dt.now.return_value = _NOW
                mock_dt.fromisoformat = datetime.fromisoformat
                deleted = ev.evict()
            # ancient (age) + old (count) = 2 evicted; mid and new survive
            self.assertEqual(len(deleted), 2)
            names = {p.name for p in deleted}
            self.assertIn("ancient.tar.gz", names)
            self.assertIn("old.tar.gz", names)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

class TestDryRun(unittest.TestCase):

    def test_dry_run_returns_list_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "old", "days_ago": 5},
                {"key": "new", "days_ago": 1},
            ])
            ev = CacheEvictor(d, max_entries=1)
            deleted = ev.evict(dry_run=True)
            self.assertEqual(len(deleted), 1)
            # File must still exist
            self.assertTrue((d / "old.tar.gz").exists())

    def test_dry_run_does_not_update_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "old", "days_ago": 5},
                {"key": "new", "days_ago": 1},
            ])
            index_before = (d / "index.json").read_text()
            ev = CacheEvictor(d, max_entries=1)
            ev.evict(dry_run=True)
            self.assertEqual((d / "index.json").read_text(), index_before)


# ---------------------------------------------------------------------------
# Index update after eviction
# ---------------------------------------------------------------------------

class TestIndexUpdate(unittest.TestCase):

    def test_evicted_key_removed_from_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "old", "days_ago": 5},
                {"key": "new", "days_ago": 1},
            ])
            ev = CacheEvictor(d, max_entries=1)
            ev.evict()
            index = json.loads((d / "index.json").read_text())
            self.assertNotIn("old", index)
            self.assertIn("new", index)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats(unittest.TestCase):

    def test_stats_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "a", "size_bytes": 100, "days_ago": 2},
                {"key": "b", "size_bytes": 200, "days_ago": 1},
            ])
            s = CacheEvictor(d).stats()
            self.assertEqual(s["count"], 2)
            self.assertGreaterEqual(s["total_mb"], 0)
            self.assertEqual(len(s["entries"]), 2)

    def test_stats_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "empty"
            d.mkdir()
            s = CacheEvictor(d).stats()
            self.assertEqual(s["count"], 0)
            self.assertEqual(s["total_mb"], 0)


# ---------------------------------------------------------------------------
# evict_from_env
# ---------------------------------------------------------------------------

class TestEvictFromEnv(unittest.TestCase):

    def test_no_env_vars_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [{"key": "x", "days_ago": 0}])
            with patch.dict("os.environ", {}, clear=True):
                deleted = evict_from_env(d)
            self.assertEqual(deleted, [])
            self.assertTrue((d / "x.tar.gz").exists())

    def test_max_entries_from_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [
                {"key": "old", "days_ago": 5},
                {"key": "mid", "days_ago": 3},
                {"key": "new", "days_ago": 1},
            ])
            env = {"NETOS_CACHE_MAX_ENTRIES": "2"}
            with patch.dict("os.environ", env):
                deleted = evict_from_env(d)
            self.assertEqual(len(deleted), 1)

    def test_invalid_env_value_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_cache_dir(tmp, [{"key": "x", "days_ago": 0}])
            env = {"NETOS_CACHE_MAX_SIZE_MB": "not-a-number"}
            with patch.dict("os.environ", env):
                # Should not raise; invalid value is ignored → falls back to no limit
                deleted = evict_from_env(d)
            # max_size_mb invalid → treated as None → no size policy → no eviction
            self.assertEqual(deleted, [])


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
