"""ArtifactSource — descriptor for where to obtain an artifact."""
from __future__ import annotations

from dataclasses import dataclass, field

# Supported source types for M1.  Git/local/oci/store are stubs for future milestones.
SOURCE_TYPES = frozenset({"url", "git", "local"})


@dataclass
class ArtifactSource:
    """Immutable descriptor for a single artifact source.

    Attributes
    ----------
    type:     One of ``"url"``, ``"git"``, ``"local"``.
    uri:      URL, git remote, or filesystem path depending on *type*.
    sha256:   Expected hex digest.  Required for ``"url"`` artifacts;
              leave empty only when the hash is genuinely unknown.
    ref:      Git branch/tag/commit (only for ``type="git"``).
    mirrors:  Fallback URLs tried in order after *uri* fails.
    timeout:  Per-attempt timeout in seconds.
    retries:  Number of download attempts (``type="url"`` only).
    """
    type:    str
    uri:     str
    sha256:  str = ""
    ref:     str = ""
    mirrors: list[str] = field(default_factory=list)
    timeout: int = 300
    retries: int = 3

    def __post_init__(self) -> None:
        if self.type not in SOURCE_TYPES:
            raise ValueError(
                f"Unknown ArtifactSource type {self.type!r}. "
                f"Supported: {sorted(SOURCE_TYPES)}"
            )
