"""Fetch and parse kernel defconfig for a given target/version."""
from __future__ import annotations

import time
import urllib.request
from typing import Optional

from fastapi import APIRouter, HTTPException

router = APIRouter()

# ── cache ──────────────────────────────────────────────────────────────────
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 3600


def _cached(key: str, fetch_fn) -> dict:
    now = time.monotonic()
    if key in _CACHE:
        ts, val = _CACHE[key]
        if now - ts < _TTL:
            return val
    val = fetch_fn()
    _CACHE[key] = (now, val)
    return val


# ── defconfig URL builders ─────────────────────────────────────────────────

def _defconfig_url(
    kernel_source: str,
    kernel_arch: str,
    defconfig: str,
    branch: Optional[str] = None,
    version: Optional[str] = None,
) -> str:
    if kernel_source == "rpi":
        br = branch or "rpi-6.12.y"
        arch_dir = "arm64" if kernel_arch == "arm64" else kernel_arch
        return (
            f"https://raw.githubusercontent.com/raspberrypi/linux/"
            f"{br}/arch/{arch_dir}/configs/{defconfig}"
        )
    # mainline
    ver = version or "6.12.27"
    # strip patch part for tag lookup: 6.12.27 -> v6.12.27
    tag = f"v{ver}"
    if kernel_arch in ("x86", "x86_64"):
        arch_dir = "x86"
    else:
        arch_dir = kernel_arch
    return (
        f"https://raw.githubusercontent.com/torvalds/linux/"
        f"{tag}/arch/{arch_dir}/configs/{defconfig}"
    )


# ── parser ─────────────────────────────────────────────────────────────────

def _parse_defconfig(text: str) -> dict[str, str]:
    """Return {CONFIG_KEY: 'y'|'m'|'n'|<value>} for all entries."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# CONFIG_") and line.endswith(" is not set"):
            key = line[2:].split(" ")[0]   # CONFIG_FOO
            result[key] = "n"
        elif line.startswith("CONFIG_") and "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _fetch_defconfig(url: str) -> dict:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "netos-configurator/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode()
        parsed = _parse_defconfig(text)
        return {"ok": True, "url": url, "config": parsed, "total": len(parsed)}
    except Exception as exc:
        return {"ok": False, "url": url, "config": {}, "error": str(exc)}


# ── target metadata (mirrors targets.py, avoid circular import) ────────────

_TARGET_META: dict[str, dict] = {
    "pi5":       {"source": "rpi",      "arch": "arm64",   "defconfig": "bcm2712_defconfig"},
    "zero2w":    {"source": "rpi",      "arch": "arm64",   "defconfig": "bcm2711_defconfig"},
    "pi4":       {"source": "rpi",      "arch": "arm64",   "defconfig": "bcm2711_defconfig"},
    "qemu-x86":  {"source": "mainline", "arch": "x86",     "defconfig": "x86_64_defconfig"},
    "qemu-virt": {"source": "mainline", "arch": "arm64",   "defconfig": "defconfig"},
    "qemu-wifi": {"source": "mainline", "arch": "arm64",   "defconfig": "defconfig"},
}


# ── endpoint ───────────────────────────────────────────────────────────────

@router.get("/kernel-config/defconfig")
def get_defconfig(
    target: str = "zero2w",
    branch: str = "",
    version: str = "",
) -> dict:
    """Return parsed defconfig for target.

    ``branch``  — RPi branch, e.g. ``rpi-6.12.y``
    ``version`` — mainline version, e.g. ``6.12.27``
    """
    meta = _TARGET_META.get(target)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown target: {target}")

    url = _defconfig_url(
        kernel_source=meta["source"],
        kernel_arch=meta["arch"],
        defconfig=meta["defconfig"],
        branch=branch or None,
        version=version or None,
    )

    cache_key = url
    result = _cached(cache_key, lambda: _fetch_defconfig(url))
    return result


# ── subsystem categoriser ──────────────────────────────────────────────────

_SUBSYSTEMS: list[tuple[str, list[str]]] = [
    ("Сеть",              ["CONFIG_NET_", "CONFIG_IP_", "CONFIG_TCP_", "CONFIG_UDP_",
                           "CONFIG_IPV6", "CONFIG_NETFILTER", "CONFIG_NF_",
                           "CONFIG_BRIDGE", "CONFIG_VLAN", "CONFIG_BONDING",
                           "CONFIG_TUN", "CONFIG_VXLAN", "CONFIG_GENEVE",
                           "CONFIG_WIREGUARD", "CONFIG_MACVLAN", "CONFIG_IPVLAN",
                           "CONFIG_L2TP", "CONFIG_PPP", "CONFIG_SLIP", "CONFIG_WAN",
                           "CONFIG_DUMMY", "CONFIG_NET_SCH", "CONFIG_NET_CLS"]),
    ("Беспроводные",      ["CONFIG_WIRELESS", "CONFIG_CFG80211", "CONFIG_MAC80211",
                           "CONFIG_WLAN", "CONFIG_ATH", "CONFIG_RTL8", "CONFIG_BRCM",
                           "CONFIG_MT76", "CONFIG_IWLWIFI", "CONFIG_HOSTAP",
                           "CONFIG_RFKILL", "CONFIG_REGULATORY"]),
    ("Bluetooth",         ["CONFIG_BT"]),
    ("USB",               ["CONFIG_USB"]),
    ("Файловые системы",  ["CONFIG_EXT2", "CONFIG_EXT3", "CONFIG_EXT4",
                           "CONFIG_BTRFS", "CONFIG_F2FS", "CONFIG_FAT", "CONFIG_VFAT",
                           "CONFIG_NTFS", "CONFIG_OVERLAY", "CONFIG_SQUASHFS",
                           "CONFIG_TMPFS", "CONFIG_NFS", "CONFIG_CIFS", "CONFIG_FUSE",
                           "CONFIG_AUTOFS", "CONFIG_ISO9660", "CONFIG_UDF",
                           "CONFIG_XFS", "CONFIG_JFS", "CONFIG_REISERFS"]),
    ("DRM / Дисплей",     ["CONFIG_DRM", "CONFIG_FB", "CONFIG_BACKLIGHT", "CONFIG_HDMI",
                           "CONFIG_LOGO"]),
    ("Звук",              ["CONFIG_SND", "CONFIG_SOUND", "CONFIG_AC97", "CONFIG_ALSA"]),
    ("Хранилище",         ["CONFIG_MMC", "CONFIG_SDHCI", "CONFIG_ATA", "CONFIG_SCSI",
                           "CONFIG_NVME", "CONFIG_BLK_DEV", "CONFIG_MD_", "CONFIG_DM_",
                           "CONFIG_IOSCHED"]),
    ("GPIO / I2C / SPI",  ["CONFIG_GPIO", "CONFIG_I2C", "CONFIG_SPI", "CONFIG_W1",
                           "CONFIG_MFD", "CONFIG_PWM"]),
    ("Контейнеры / Virt", ["CONFIG_CGROUP", "CONFIG_NAMESPACES", "CONFIG_USER_NS",
                           "CONFIG_KVM", "CONFIG_VHOST", "CONFIG_VIRTIO", "CONFIG_VSOCK",
                           "CONFIG_MEMCG", "CONFIG_CPUSETS", "CONFIG_OVERLAY_FS"]),
    ("Безопасность",      ["CONFIG_SECURITY", "CONFIG_SECCOMP", "CONFIG_IMA",
                           "CONFIG_CRYPTO", "CONFIG_KEYS", "CONFIG_TRUSTED",
                           "CONFIG_ENCRYPTED", "CONFIG_INTEGRITY", "CONFIG_AUDIT"]),
    ("Отладка / Trace",   ["CONFIG_DEBUG", "CONFIG_FTRACE", "CONFIG_KPROBE",
                           "CONFIG_PERF", "CONFIG_TRACE", "CONFIG_KALLSYMS",
                           "CONFIG_KASAN", "CONFIG_UBSAN"]),
    ("Платформа / SOC",   ["CONFIG_ARCH_", "CONFIG_MACH_", "CONFIG_PLAT_",
                           "CONFIG_SOC_", "CONFIG_BCM2", "CONFIG_RASPBERRYPI",
                           "CONFIG_PINCTRL", "CONFIG_REGULATOR", "CONFIG_CLK_",
                           "CONFIG_RESET_"]),
    ("Планировщик / CPU", ["CONFIG_HZ", "CONFIG_PREEMPT", "CONFIG_SMP",
                           "CONFIG_CPU_", "CONFIG_SCHED_", "CONFIG_RCU_",
                           "CONFIG_TICK_", "CONFIG_NO_HZ", "CONFIG_NUMA"]),
    ("Память",            ["CONFIG_MEMORY_", "CONFIG_SWAP", "CONFIG_ZSWAP",
                           "CONFIG_ZRAM", "CONFIG_BALLOON", "CONFIG_HUGETLB",
                           "CONFIG_TRANSPARENT_HUGEPAGE", "CONFIG_COMPACTION"]),
    ("Прочее",            []),   # catch-all
]


def _categorize_config(config: dict[str, str]) -> list[dict]:
    assigned: set[str] = set()
    result = []
    for cat_name, prefixes in _SUBSYSTEMS:
        if not prefixes:          # catch-all at end
            items = {k: v for k, v in config.items() if k not in assigned}
        else:
            items = {
                k: v for k, v in config.items()
                if k not in assigned and any(k.startswith(p) for p in prefixes)
            }
        if items:
            assigned.update(items.keys())
            result.append({
                "category": cat_name,
                "items": [
                    {"key": k, "value": v,
                     "config": f"{k}={v}" if v != "n" else f"# {k} is not set"}
                    for k, v in sorted(items.items())
                ],
            })
    return result


@router.get("/kernel-config/browse")
def browse_defconfig(
    target: str = "zero2w",
    branch: str = "",
    version: str = "",
    section: str = "all",   # all | y | m | n
) -> list:
    """Return all defconfig options grouped by subsystem category.

    ``section`` filters by value: ``y`` built-in, ``m`` module, ``n`` disabled, ``all``.
    """
    meta = _TARGET_META.get(target)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown target: {target}")

    url = _defconfig_url(
        kernel_source=meta["source"],
        kernel_arch=meta["arch"],
        defconfig=meta["defconfig"],
        branch=branch or None,
        version=version or None,
    )
    result = _cached(url, lambda: _fetch_defconfig(url))
    if not result.get("ok"):
        return []

    cfg = result["config"]
    if section != "all":
        cfg = {k: v for k, v in cfg.items() if v == section}

    return _categorize_config(cfg)
