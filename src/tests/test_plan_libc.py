"""Libc-awareness of the build plan + toolchain cache keys.

Guarantees:
  * glibc targets keep byte-identical toolchain cache keys (no cache
    invalidation from the libc parametrization).
  * musl targets get a distinct key, the musl defconfig symbol, and the
    *-linux-musl toolchain triple.

Run:
    python -m pytest src/tests/test_plan_libc.py -v
"""
from __future__ import annotations

import dataclasses
import hashlib
import sys
from pathlib import Path

_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from netos_build.plan import ResolvedBuildPlan
from netos_build.toolchain_cache import ToolchainCache
from targets import TARGETS


def _legacy_glibc_key(p: ResolvedBuildPlan) -> str:
    raw = "\n".join([
        p.buildroot_arch,
        p.cross_compile,
        "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y",
        "BR2_TOOLCHAIN_BUILDROOT_CXX=y",
    ])
    return f"{p.arch}-{hashlib.md5(raw.encode()).hexdigest()[:8]}"


def _musl_mips_target():
    return dataclasses.replace(
        TARGETS["zero2w"],
        name="mt7628",
        buildroot_arch="mipsel",
        cross_compile="mipsel-linux-",
        libc="musl",
        rootfs_type="squashfs",
    )


def test_glibc_plan_key_unchanged():
    for name in ("zero2w", "pi5", "pi4"):
        p = ResolvedBuildPlan.from_target(TARGETS[name])
        assert p.libc == "glibc"
        assert p.toolchain_libc_symbol == "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y"
        assert p.toolchain_cache_key() == _legacy_glibc_key(p), name


def test_musl_plan_key_distinct():
    g = ResolvedBuildPlan.from_target(TARGETS["zero2w"])
    m = ResolvedBuildPlan.from_target(_musl_mips_target())
    assert m.libc == "musl"
    assert m.toolchain_libc_symbol == "BR2_TOOLCHAIN_BUILDROOT_MUSL=y"
    assert m.arch == "mipsel"
    assert m.toolchain_cache_key() != g.toolchain_cache_key()
    assert m.toolchain_cache_key().startswith("mipsel-")


def test_toolchain_cache_key_glibc_unchanged():
    cache = ToolchainCache(Path("/tmp/does-not-matter"))
    p = ResolvedBuildPlan.from_target(TARGETS["zero2w"])
    raw = "\n".join([
        p.buildroot_arch, p.cross_compile, "2026.02.1",
        "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y", "BR2_TOOLCHAIN_BUILDROOT_CXX=y",
    ])
    legacy = f"{p.arch}-br2026.02.1-{hashlib.md5(raw.encode()).hexdigest()[:8]}"
    assert cache.cache_key(p, "2026.02.1") == legacy


def test_toolchain_cache_key_musl_distinct():
    cache = ToolchainCache(Path("/tmp/does-not-matter"))
    g = ResolvedBuildPlan.from_target(TARGETS["zero2w"])
    m = ResolvedBuildPlan.from_target(_musl_mips_target())
    assert cache.cache_key(m, "2026.02.1") != cache.cache_key(g, "2026.02.1")
