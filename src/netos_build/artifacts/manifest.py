"""ArtifactManifest — metadata record for a cached/stored artifact."""
from __future__ import annotations

from dataclasses import dataclass, field

# Valid artifact format tags
ARTIFACT_FORMATS = frozenset({
    "source-archive",   # upstream tarball (buildroot, kernel, ovs, …)
    "toolchain",        # pre-built cross-compiler archive  (M3)
    "rootfs-overlay",   # rootfs overlay tarball             (M5)
    "kernel",           # compiled kernel image
    "image",            # final disk image
})


@dataclass
class ArtifactManifest:
    """Lightweight metadata attached to every cached artifact.

    Only ``name``, ``version``, ``arch``, ``format``, and ``sha256``
    are required for M1.  The rest are filled in by later milestones.
    """
    name:     str
    version:  str
    arch:     str   # "arm64" | "x86_64" | "any"
    format:   str   # see ARTIFACT_FORMATS

    # Content identity
    sha256:   str
    size:     int  = 0
    source_url: str = ""

    # Build provenance (filled in by toolchain/rootfs cache — M3/M5)
    build_id:   str = ""
    target:     str = ""   # "qemu-virt", "pi5", …
    cached_at:  str = ""

    # Future: runtime_deps, build_deps — intentionally omitted in v0
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.format not in ARTIFACT_FORMATS:
            raise ValueError(
                f"Unknown artifact format {self.format!r}. "
                f"Supported: {sorted(ARTIFACT_FORMATS)}"
            )
