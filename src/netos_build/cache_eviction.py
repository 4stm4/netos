"""CacheEvictor — LRU / age-based eviction for local artifact caches.

Keeps ``temp/cache/toolchains/`` and ``temp/cache/rootfs/`` from growing
unboundedly.  Three independent policies can be combined:

  max_size_mb   — delete oldest entries until total size ≤ limit
  max_age_days  — delete entries packed more than N days ago
  max_entries   — delete oldest entries until count ≤ limit

All three default to *unlimited* (None).  When multiple policies are set,
**all** are applied — the result is the union of what each policy decided
to delete.

Entry age is read from ``index.json`` (the ``packed_at`` ISO-8601 field
written by ToolchainCache / RootfsCache).  If an archive file exists on
disk but has no index entry, it is treated as age=now (never evicted by
age alone, but counted for size/count).

Configuration via environment variables
----------------------------------------
NETOS_CACHE_MAX_SIZE_MB     Max total size in MB for *each* cache dir
                             (toolchains and rootfs are counted separately)
NETOS_CACHE_MAX_AGE_DAYS    Delete entries older than N days
NETOS_CACHE_MAX_ENTRIES     Keep at most N entries per cache dir

Usage
-----
Programmatic::

    from netos_build.cache_eviction import CacheEvictor
    ev = CacheEvictor(cache_dir, max_size_mb=2048, max_age_days=30)
    deleted = ev.evict()

From CLI (dry-run)::

    python -m netos_build.cache_eviction --cache-dir temp/cache --dry-run

Called automatically after every successful pack in NetOSBuildrootBuilder.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_INDEX_FILE = "index.json"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(order=False)
class _Entry:
    key:       str
    path:      Path
    size_bytes: int
    packed_at: datetime

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1e6

    def age_days(self, now: datetime) -> float:
        return (now - self.packed_at).total_seconds() / 86400


# ---------------------------------------------------------------------------
# CacheEvictor
# ---------------------------------------------------------------------------

class CacheEvictor:
    """Apply LRU / age / count eviction policies to a single cache directory."""

    def __init__(
        self,
        cache_dir: Path,
        max_size_mb:   float | None = None,
        max_age_days:  float | None = None,
        max_entries:   int   | None = None,
    ) -> None:
        self.cache_dir    = Path(cache_dir)
        self.max_size_mb  = max_size_mb
        self.max_age_days = max_age_days
        self.max_entries  = max_entries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evict(self, dry_run: bool = False) -> list[Path]:
        """Run all configured policies and delete the selected archives.

        Returns the list of archive paths that were (or would be) deleted.
        When *dry_run* is True, nothing is deleted but the list is returned.
        """
        if not self.cache_dir.exists():
            return []

        entries = self._load_entries()
        if not entries:
            return []

        now      = datetime.now(tz=timezone.utc)
        to_evict: set[str] = set()

        if self.max_age_days is not None:
            to_evict |= self._by_age(entries, now)
        if self.max_size_mb is not None:
            to_evict |= self._by_size(entries)
        if self.max_entries is not None:
            to_evict |= self._by_count(entries)

        deleted: list[Path] = []
        for e in entries:
            if e.key not in to_evict:
                continue
            if dry_run:
                logging.info(
                    "CacheEvictor [dry-run]: would delete %s (%.1f MB, %.0f days old)",
                    e.path.name, e.size_mb, e.age_days(now),
                )
            else:
                logging.info(
                    "CacheEvictor: deleting %s (%.1f MB, %.0f days old)",
                    e.path.name, e.size_mb, e.age_days(now),
                )
                e.path.unlink(missing_ok=True)
            deleted.append(e.path)

        if deleted and not dry_run:
            self._update_index(to_evict)
            remaining = [e for e in entries if e.key not in to_evict]
            total_mb  = sum(e.size_mb for e in remaining)
            logging.info(
                "CacheEvictor: evicted %d entr%s from %s — %d remain (%.1f MB total)",
                len(deleted), "y" if len(deleted) == 1 else "ies",
                self.cache_dir.name, len(remaining), total_mb,
            )

        return deleted

    def stats(self) -> dict[str, Any]:
        """Return a summary dict of current cache state (for logging/CLI)."""
        entries = self._load_entries()
        now     = datetime.now(tz=timezone.utc)
        return {
            "count":      len(entries),
            "total_mb":   round(sum(e.size_mb for e in entries), 1),
            "oldest_days": round(max((e.age_days(now) for e in entries), default=0), 1),
            "newest_days": round(min((e.age_days(now) for e in entries), default=0), 1),
            "entries": [
                {
                    "key":      e.key,
                    "size_mb":  round(e.size_mb, 1),
                    "age_days": round(e.age_days(now), 1),
                    "packed_at": e.packed_at.isoformat(),
                }
                for e in sorted(entries, key=lambda x: x.packed_at)
            ],
        }

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------

    def _by_age(self, entries: list[_Entry], now: datetime) -> set[str]:
        assert self.max_age_days is not None
        cutoff = now - timedelta(days=self.max_age_days)
        return {e.key for e in entries if e.packed_at < cutoff}

    def _by_size(self, entries: list[_Entry]) -> set[str]:
        assert self.max_size_mb is not None
        # Sort oldest-first
        ordered = sorted(entries, key=lambda e: e.packed_at)
        total   = sum(e.size_bytes for e in ordered) / 1e6
        evict:  set[str] = set()
        for e in ordered:
            if total <= self.max_size_mb:
                break
            evict.add(e.key)
            total -= e.size_mb
        return evict

    def _by_count(self, entries: list[_Entry]) -> set[str]:
        assert self.max_entries is not None
        if len(entries) <= self.max_entries:
            return set()
        ordered = sorted(entries, key=lambda e: e.packed_at)
        excess  = len(ordered) - self.max_entries
        return {e.key for e in ordered[:excess]}

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------

    def _load_entries(self) -> list[_Entry]:
        """Build entry list from index.json + filesystem scan."""
        index = self._read_index()
        entries: list[_Entry] = []
        _now = datetime.now(tz=timezone.utc)

        # Archives present on disk (source of truth for existence)
        on_disk: dict[str, Path] = {}
        for ext in ("*.tar.gz", "*.rootfs.tar.gz"):
            for p in self.cache_dir.glob(ext):
                if p.name == _INDEX_FILE:
                    continue
                on_disk[p.stem.split(".")[0] + ("." + ".".join(p.name.split(".")[1:])
                        if "." in p.name else "")] = p

        # Re-key on_disk by filename stem for lookup
        on_disk_by_name: dict[str, Path] = {p.name: p for p in on_disk.values()}

        for name, path in on_disk_by_name.items():
            size = path.stat().st_size if path.exists() else 0
            # Find index entry by matching archive filename
            meta: dict[str, Any] = {}
            for key, entry in index.items():
                if entry.get("archive_name", "") == name or name.startswith(key):
                    meta = entry
                    break
            if not meta:
                # Try matching by key prefix
                stem = name.replace(".rootfs.tar.gz", "").replace(".tar.gz", "")
                meta = index.get(stem, {})

            packed_at_str = meta.get("packed_at", "")
            try:
                packed_at = datetime.fromisoformat(packed_at_str)
                if packed_at.tzinfo is None:
                    packed_at = packed_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                packed_at = _now

            # Prefer size_bytes from index (accurate even for test stubs);
            # fall back to actual file size on disk.
            index_size = meta.get("size_bytes")
            if index_size is not None:
                try:
                    size = int(index_size)
                except (ValueError, TypeError):
                    pass  # keep disk size

            # key = stem without extension
            key = name.replace(".rootfs.tar.gz", "").replace(".tar.gz", "")
            entries.append(_Entry(
                key=key,
                path=path,
                size_bytes=size,
                packed_at=packed_at,
            ))

        return entries

    def _read_index(self) -> dict[str, Any]:
        p = self.cache_dir / _INDEX_FILE
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
        return {}

    def _update_index(self, evicted_keys: set[str]) -> None:
        """Remove evicted entries from index.json."""
        index = self._read_index()
        for key in list(index.keys()):
            if key in evicted_keys:
                del index[key]
        p = self.cache_dir / _INDEX_FILE
        p.write_text(json.dumps(index, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Factory from environment variables
# ---------------------------------------------------------------------------

def evict_from_env(cache_dir: Path, dry_run: bool = False) -> list[Path]:
    """Run eviction on *cache_dir* using env-var policy config.

    Returns list of deleted (or would-be-deleted) paths.
    Does nothing if no env vars are set.
    """
    max_size_mb  = _env_float("NETOS_CACHE_MAX_SIZE_MB")
    max_age_days = _env_float("NETOS_CACHE_MAX_AGE_DAYS")
    max_entries  = _env_int("NETOS_CACHE_MAX_ENTRIES")

    if max_size_mb is None and max_age_days is None and max_entries is None:
        return []   # no policy configured

    ev = CacheEvictor(
        cache_dir,
        max_size_mb=max_size_mb,
        max_age_days=max_age_days,
        max_entries=max_entries,
    )
    return ev.evict(dry_run=dry_run)


def _env_float(name: str) -> float | None:
    v = os.environ.get(name, "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        logging.warning("Invalid value for %s=%r — ignoring", name, v)
        return None


def _env_int(name: str) -> int | None:
    v = _env_float(name)
    return int(v) if v is not None else None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse, sys

    parser = argparse.ArgumentParser(
        description="Evict old entries from netos artifact caches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show current cache state
  python -m netos_build.cache_eviction --cache-dir temp/cache --dry-run

  # Keep at most 3 GB per cache dir, delete entries older than 14 days
  python -m netos_build.cache_eviction \\
      --cache-dir temp/cache \\
      --max-size-mb 3072 \\
      --max-age-days 14

  # Keep only 2 most-recent entries per dir (useful for CI cleanup)
  python -m netos_build.cache_eviction --cache-dir temp/cache --max-entries 2
""",
    )
    parser.add_argument("--cache-dir", required=True,
                        help="Path to the cache root (contains toolchains/ and rootfs/)")
    parser.add_argument("--max-size-mb",  type=float, default=None,
                        help="Max total size in MB per cache dir (oldest deleted first)")
    parser.add_argument("--max-age-days", type=float, default=None,
                        help="Delete entries older than N days")
    parser.add_argument("--max-entries",  type=int,   default=None,
                        help="Keep at most N entries per cache dir")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be deleted without deleting anything")
    parser.add_argument("--stats", action="store_true",
                        help="Print current cache statistics and exit")
    args = parser.parse_args()

    cache_root = Path(args.cache_dir)
    subdirs    = ["toolchains", "rootfs"]

    for subdir in subdirs:
        d = cache_root / subdir
        ev = CacheEvictor(
            d,
            max_size_mb  = args.max_size_mb,
            max_age_days = args.max_age_days,
            max_entries  = args.max_entries,
        )
        if args.stats:
            s = ev.stats()
            print(f"\n{subdir}/: {s['count']} entries, "
                  f"{s['total_mb']} MB total, "
                  f"oldest {s['oldest_days']} days")
            for e in s["entries"]:
                print(f"  {e['key'][:60]:<60}  {e['size_mb']:>7.1f} MB  "
                      f"{e['age_days']:>5.0f} days  {e['packed_at']}")
        else:
            deleted = ev.evict(dry_run=args.dry_run)
            if not deleted:
                print(f"{subdir}/: nothing to evict")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _cli()
