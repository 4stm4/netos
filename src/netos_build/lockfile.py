"""LockFile — reads and writes ``netos.lock.json``.

The lock file pins the exact source artifact versions and SHA-256 hashes
used in a build, enabling:
  - Reproducible builds (same lock → same inputs)
  - Offline use (no network needed if all artifacts are cached)
  - Audit trail (lock committed to git alongside the build definition)

Layout::

    {
      "version": 1,
      "generated_at": "2026-05-26T12:00:00+00:00",
      "artifacts": {
        "buildroot": {
          "version": "2026.02.1",
          "url":     "https://buildroot.org/downloads/buildroot-2026.02.1.tar.xz",
          "sha256":  "a2216fdc..."
        },
        "linux-mainline": {
          "version": "6.12.27",
          "url":     "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.27.tar.xz",
          "sha256":  ""
        },
        "openvswitch": {
          "version": "3.4.1",
          "url":     "https://www.openvswitch.org/releases/openvswitch-3.4.1.tar.gz",
          "sha256":  "6e97ec7d..."
        }
      }
    }

Usage::

    lock = LockFile(project_root / "netos.lock.json")
    lock.load()

    # Override ArtifactManager sha256 with the locked value (if present):
    sha256 = lock.sha256_for("buildroot") or BUILDROOT_SHA256

    # After a successful build, record what was actually used:
    lock.record("buildroot", version=BUILDROOT_VERSION,
                url=BUILDROOT_URL, sha256=BUILDROOT_SHA256)
    lock.save()
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK_VERSION = 1


class LockFile:
    """Read/write interface for ``netos.lock.json``."""

    def __init__(self, path: Path) -> None:
        self.path   = Path(path)
        self._data: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """Load the lock file from disk.  Returns ``True`` if it was found."""
        if not self.path.exists():
            logging.debug("Lock file not found: %s", self.path)
            return False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version", 0) != _LOCK_VERSION:
                logging.warning(
                    "Lock file %s has unsupported version %s — ignoring",
                    self.path, raw.get("version"),
                )
                return False
            self._data = raw
            logging.info("Loaded lock file: %s", self.path)
            return True
        except Exception as exc:
            logging.warning("Failed to load lock file %s: %s", self.path, exc)
            return False

    def save(self) -> None:
        """Flush the in-memory state to ``self.path``."""
        artifacts = self._data.get("artifacts", {})
        out = {
            "version":      _LOCK_VERSION,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "artifacts":    artifacts,
        }
        self.path.write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logging.info("Lock file saved: %s", self.path)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def record(
        self,
        name:    str,
        version: str,
        url:     str,
        sha256:  str = "",
    ) -> None:
        """Record or update an artifact entry in the in-memory state.

        Call :meth:`save` afterwards to persist to disk.
        """
        if "artifacts" not in self._data:
            self._data["artifacts"] = {}
        self._data["artifacts"][name] = {
            "version": version,
            "url":     url,
            "sha256":  sha256,
        }

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> dict[str, Any] | None:
        """Return the full entry for *name*, or ``None`` if absent."""
        return self._data.get("artifacts", {}).get(name)

    def sha256_for(self, name: str) -> str | None:
        """Return the pinned SHA-256 for *name*, or ``None`` if not set."""
        entry = self.get(name)
        if entry:
            value = entry.get("sha256", "").strip()
            return value if value else None
        return None

    def version_for(self, name: str) -> str | None:
        """Return the pinned version string for *name*, or ``None``."""
        entry = self.get(name)
        return entry.get("version") if entry else None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_sha256(self, name: str, actual_sha256: str) -> None:
        """Raise ``RuntimeError`` if the lock file SHA-256 for *name* does
        not match *actual_sha256*.  No-op if *name* is not in the lock file
        or has no SHA-256.
        """
        expected = self.sha256_for(name)
        if expected and expected != actual_sha256.lower().strip():
            raise RuntimeError(
                f"Lock file violation for artifact '{name}':\n"
                f"  lock file : {expected}\n"
                f"  actual    : {actual_sha256}\n"
                f"Run with cache_policy='refresh' or update netos.lock.json."
            )

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        n = len(self._data.get("artifacts", {}))
        return f"LockFile({self.path}, {n} artifact(s))"
