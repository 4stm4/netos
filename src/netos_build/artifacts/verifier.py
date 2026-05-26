"""SHA-256 verification utilities."""
from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 20  # 1 MB — stream large files without loading all into memory


def sha256_file(path: Path) -> str:
    """Return lower-hex SHA-256 digest of *path*, streaming in 1 MB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, expected: str) -> bool:
    """Return True iff the file's SHA-256 matches *expected* (case-insensitive)."""
    return sha256_file(path) == expected.lower().strip()
