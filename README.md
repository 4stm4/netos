# netOS

A from-source ARM64/x86_64 appliance OS for network and virtualization nodes.

Built from scratch: Linux kernel, minimal userspace (Buildroot), Open vSwitch / OVSDB, management agents, Web UI (Testum) and SDN controller (Nervum). Produces a ready-to-flash raw disk image.

**This is not an Ubuntu/Debian rootfs.** The target system has no `apt`, `dpkg`, or `docker`. Buildroot manages the entire userspace.

## Quick Start

```bash
# Build an image for QEMU (ARM64)
python3 src/main.py --target qemu-virt

# Run and verify
python3 src/run_qemu.py --target qemu-virt
```

First build takes 30–90 minutes; subsequent builds are incremental.

## Targets

| Target | Architecture | Kernel | Image | Size |
|---|---|---|---|---|
| `qemu-virt` | ARM64 | mainline 6.12 | `qemu-virt.img` | 512 MB |
| `qemu-x86` | x86\_64 | mainline 6.12 | `qemu-x86.img` | 512 MB |
| `pi5` | ARM64 | rpi-6.12.y | `raspi.img` | 1024 MB |
| `pi4` | ARM64 | rpi-6.12.y | `raspi-pi4.img` | 1024 MB |
| `zero2w` | ARM64 | rpi-6.12.y | `raspi-zero2w.img` | 1024 MB |

## Web Configurator

A browser-based interface for configuring and launching builds:

```bash
python3 src/configurator/serve.py --host 0.0.0.0 --port 5173
```

Open: `http://localhost:5173`

Features: target selection, kernel version picker (RPi branches and mainline up to 7.x), kernel config browser, package manager, build cache manager, build history with live log streaming.

## Documentation

- [Build](docs/build.md) — requirements, commands, profiles, environment variables
- [Targets](docs/targets.md) — per-target description, kernel, architecture
- [QEMU](docs/qemu.md) — running in QEMU, port forwarding, x86 vs ARM
- [Configurator](docs/configurator.md) — web UI, wizard steps, profiles
- [Packages](docs/packages.md) — adding packages, presets, custom BR2_PACKAGE
- [Networking](docs/networking.md) — eth0, Wi-Fi, Open vSwitch / OVSDB
- [Environment Variables](docs/env-reference.md) — full NETOS_* reference

## Build Host Requirements

- Linux (macOS — only via Lima VM or remote builder)
- Python 3.10+
- Do not run as root — `sudo` is called automatically only for `mount`/`losetup`
- ~10 GB free disk space

## License

See [LICENSE](LICENSE) (GPL v3).
