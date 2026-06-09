# netOS

A from-source embedded OS builder for ARM64 and x86_64 network appliances.

Compiles Linux kernel + Buildroot userspace into a raw disk image ready to flash or boot in QEMU. No Ubuntu/Debian rootfs — the target system has no `apt`, `dpkg`, or `docker`; Buildroot owns the entire userspace.

Current component versions: **Buildroot 2026.02.1**, **Open vSwitch 3.4.1**, Linux kernel up to **7.x** (mainline) or **rpi-6.12.y** (RPi).

---

## Targets

| Target | Arch | Kernel | Image | Size |
|---|---|---|---|---|
| `qemu-virt` | ARM64 | mainline | `qemu-virt.img` | 512 MB |
| `qemu-x86` | x86\_64 | mainline | `qemu-x86.img` | 512 MB |
| `qemu-wifi` | ARM64 | mainline + mac80211\_hwsim | `qemu-wifi.img` | 512 MB |
| `pi5` | ARM64 | rpi-6.12.y | `raspi.img` | 1024 MB |
| `pi4` | ARM64 | rpi-6.12.y | `raspi-pi4.img` | 1024 MB |
| `zero2w` | ARM64 | rpi-6.12.y | `raspi-zero2w.img` | 192 MB |

All RPi targets support mainline kernel via `NETOS_KERNEL_SOURCE=mainline`.

## Appliances

Appliances are composable profiles layered on top of a base target:

| Appliance | Description |
|---|---|
| `netos` *(default)* | Networking node — OVS/OVSDB, management agents, Web UI, Nervum SDN |
| `tinywifi` | Minimal Wi-Fi AP — hostapd, nanodhcp, nftables NAT, TinyWifi web UI |

Set via `NETOS_APPLIANCE=tinywifi`.

---

## Quick Start

```bash
# Build for QEMU ARM64
python3 src/main.py --target qemu-virt

# Run in QEMU
python3 src/run_qemu.py --target qemu-virt
```

```bash
# Build TinyWifi AP for Raspberry Pi Zero 2W
NETOS_APPLIANCE=tinywifi python3 src/main.py --target zero2w

# Flash to SD card
dd if=builds/raspi-zero2w.img of=/dev/sdX bs=4M status=progress
```

First build: 30–90 min. Subsequent builds use toolchain and rootfs cache.

---

## Web Configurator

A browser-based UI for configuring and launching builds without touching environment variables:

```bash
python3 -m uvicorn "src.configurator.app:create_app" --host 0.0.0.0 --port 5173
```

Open `http://localhost:5173`.

**Wizard steps:**
1. Environment (presets: TinyWifi AP, QEMU x86, QEMU ARM64, RPi 5, Zero 2W + Wi-Fi, …)
2. Target
3. Kernel version — RPi branches and mainline up to 7.x, selectable for any target
4. Kernel options (CONFIG_* browser, ~1700 items from real defconfig)
5. Kernel modules
6. Kernel drivers
7. Branding & networking
8. Packages (catalog groups + custom BR2_PACKAGE_*)
9. Web UI & Nervum SDN
10. Build — live log streaming, build history

**Package & kernel cache manager** (`📦 Cache` in sidebar):
- Browse Buildroot `dl/` cache, pre-download packages by URL
- Pre-fetch Linux kernel tarballs (RPi branches or mainline) before the build starts
- Background download jobs with live log

---

## Build Host Requirements

- Linux x86\_64 or ARM64 (macOS — only via Lima VM or SSH to a Linux builder)
- Python 3.10+
- `sudo` access for `mount` / `losetup` during image creation
- ~10 GB free disk space

Do not run as root — `sudo` is called automatically only where needed.

---

## Key Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NETOS_APPLIANCE` | `netos` | `netos` or `tinywifi` |
| `NETOS_TARGET` | — | Target name (alternative to `--target`) |
| `NETOS_KERNEL_SOURCE` | `rpi` | `rpi` or `mainline` |
| `NETOS_KERNEL_BRANCH` | `rpi-6.12.y` | RPi kernel branch |
| `NETOS_MAINLINE_KERNEL_VERSION` | `6.12.27` | Mainline version to download |
| `NETOS_KERNEL_CONFIG_OPTIONS` | — | Space-separated `CONFIG_*=y/m/n` overrides |
| `NETOS_BUILD_JOBS` | CPU count | Parallel build jobs |
| `NETOS_BUILDROOT_VERSION` | `2026.02.1` | Buildroot version |
| `NETOS_CACHE_DIR` | `temp/cache` | Toolchain / rootfs cache directory |
| `NETOS_CACHE_POLICY` | `use` | `use`, `rebuild`, or `ignore` |
| `NETOS_HOSTNAME` | `netos` | Target hostname |
| `NETOS_VERSION` | `0.1.0` | OS version string |
| `NETOS_IMAGE_SIZE_MB` | target default | Root partition size |
| `NETOS_WIFI_SSID` | — | Wi-Fi AP SSID (TinyWifi) |
| `NETOS_WIFI_PSK` | — | Wi-Fi AP passphrase |
| `NETOS_WIFI_COUNTRY` | — | Wi-Fi regulatory country code |
| `NETOS_BUILDS_DIR` | `builds/` | Where the configurator stores build records |

Full reference: [docs/env-reference.md](docs/env-reference.md)

---

## Project Layout

```
src/
  main.py                  — build entry point
  targets.py               — target definitions (kernel options, partitions, DTBs)
  adapters/
    linux_kernel.py        — kernel download, configure, compile, modules
    netos_buildroot.py     — Buildroot orchestration, OVS, package selection
    package_installer.py   — host build dependency installer
    tinywifi_setup.py      — TinyWifi rootfs provisioner
    network_adapter.py     — OVS/OVSDB configuration
  agents/
    net_agent.py           — network management agent
    vm_agent.py            — VM/container agent
    storage_agent.py       — storage agent
    stat_agent.py          — metrics agent
  configurator/            — web UI (FastAPI + Alpine.js)
    routes/
      pkg_cache.py         — package & kernel cache manager API
      kernel_config.py     — defconfig browser API
      builds.py            — build runner API + SSE log streaming
  netos_build/             — build plan, toolchain/rootfs cache, artifact store
  make_image.py            — disk image creation (partition, format, populate)
  run_qemu.py              — QEMU launch helper
```

---

## License

[GPL v3](LICENSE)
