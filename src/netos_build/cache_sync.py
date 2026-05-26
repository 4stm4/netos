"""CacheSync — bridge between local caches (M3/M5) and a remote ArtifactStore.

Usage pattern
-------------
**pull** (before local restore)::

    sync = CacheSync(store)
    sync.pull(archive_name, local_archive_path)   # fetches from remote if missing
    # then call toolchain_cache.restore(...)

**push** (after local pack)::

    # toolchain_cache.pack(...) wrote the archive locally
    sync.push(archive_name, local_archive_path)   # uploads to remote store

This two-step pattern means local cache always wins (fastest path), and
remote store is used as a transparent backing layer.

Non-fatal
---------
All errors during pull/push are logged but never propagate — a store
failure must not abort the build.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from netos_build.store import ArtifactStore


class CacheSync:
    """Pull from and push to a remote ArtifactStore around local cache operations."""

    def __init__(self, store: "ArtifactStore", push_enabled: bool = True) -> None:
        self.store        = store
        self.push_enabled = push_enabled

    @property
    def active(self) -> bool:
        """True when the store actually does remote I/O."""
        return not self.store.is_local

    # ------------------------------------------------------------------

    def pull(self, remote_key: str, local_path: Path) -> bool:
        """Download *remote_key* into *local_path* if not already present.

        Returns True if local_path now exists (either it was already there
        or was just downloaded).  Returns False on store miss or error.
        """
        if local_path.exists():
            return True                   # already cached locally

        if self.store.is_local:
            return False

        try:
            if self.store.download(remote_key, local_path):
                logging.info("CacheSync: pulled %s from remote store", remote_key)
                return True
            logging.debug("CacheSync: remote miss for %s", remote_key)
            return False
        except Exception as exc:
            logging.warning(
                "CacheSync: pull failed for %s (%s) — continuing without remote cache",
                remote_key, exc,
            )
            local_path.unlink(missing_ok=True)
            return False

    def push(self, remote_key: str, local_path: Path) -> bool:
        """Upload *local_path* to the remote store under *remote_key*.

        Skipped when:
        * push_enabled is False (read-only mode via NETOS_STORE_PUSH=0)
        * store is local
        * remote already has this key (no-op)
        * local_path does not exist

        Always returns True (failure is non-fatal).
        """
        if not self.push_enabled or self.store.is_local:
            return False

        if not local_path.exists():
            return False

        try:
            if self.store.exists(remote_key):
                logging.debug("CacheSync: remote already has %s — skipping push", remote_key)
                return True
            if self.store.upload(remote_key, local_path):
                logging.info("CacheSync: pushed %s to remote store", remote_key)
                return True
        except Exception as exc:
            logging.warning(
                "CacheSync: push failed for %s (%s) — cache stored locally only",
                remote_key, exc,
            )
        return False
