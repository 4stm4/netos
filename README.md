# 4stm4 NetOS

4stm4 NetOS - это собираемая из исходников ARM64 appliance OS для сетевого/виртуализационного узла. Проект собирает Linux kernel, минимальный userspace через Buildroot, Open vSwitch/OVSDB, системную OVSDB-схему, агенты управления и готовый raw-образ диска.

Целевая система не является Ubuntu/Debian rootfs. Внутри target rootfs нет `apt`, `dpkg`, `mmdebstrap`, `debootstrap` и Docker-зависимостей. Ubuntu/Linux VM используется только как среда сборки на хосте.

## Текущий Статус

- Рабочий локальный target: `qemu-virt`.
- Собран и проверен образ: `qemu-virt.img`.
- Внутри rootfs branding: `NAME="4stm4 NetOS"`, `ID=4stm4-netos`.
- QEMU boot-test проходит: rootfs монтируется, сеть поднимается, `dropbear` стартует, `ovsdb-server` доступен через host-forward.
- Для полноценного Open vSwitch datapath еще нужно пересобрать kernel с поддержкой `ovs_datapath`; сейчас OVSDB и `ovs-vswitchd` стартуют, но kernel datapath в текущем prebuilt kernel отсутствует.

## Что Собирается

- ARM64 Linux kernel.
- Buildroot rootfs `4stm4 NetOS`.
- Open vSwitch userspace: `ovsdb-server`, `ovs-vswitchd`, CLI tools и Python-модули.
- `/etc/os-release`, `/usr/lib/os-release`, hostname, issue и базовые системные конфиги.
- OVSDB schema: `src/schema/system.ovsschema`.
- Management agents:
  - `net_agent.py` - сетевые интерфейсы, bridge/state, hostname/timezone/log level.
  - `storage_agent.py` - iSCSI login и mount workflow.
  - `vm_agent.py` - управление VM-процессами и cgroup assignment.
  - `stat_agent.py` - телеметрия.
- Init hook `S99netos`, который поднимает OVSDB, Open vSwitch, агентов и watchdog loop.
- Raw disk image с двумя разделами: FAT boot и ext4 rootfs.

## Targets

- `qemu-virt` - generic ARM64 QEMU `virt` image для локальной проверки. Output: `qemu-virt.img`.
- `pi5` - Raspberry Pi 5 / BCM2712 hardware image. Output: `raspi.img`.

`qemu-virt` проверен локально. `pi5` требует отдельной проверки на реальном Raspberry Pi 5.

## Основные Файлы

- `src/main.py` - главный entrypoint сборки.
- `src/targets.py` - target profiles: kernel defconfig, имя образа, boot cmdline, QEMU machine.
- `src/netos_branding.py` - имя ОС, `ID`, hostname, версия.
- `src/adapters/netos_buildroot.py` - Buildroot version, external tree, defconfig, overlay, пакет Open vSwitch.
- `src/adapters/linux_kernel.py` - подготовка/сборка kernel или подключение prebuilt `Image`.
- `src/core/container_setup.py` - финальная настройка rootfs, `/etc/os-release`, init-скрипт, OVSDB schema и агенты.
- `src/make_image.py` - создание raw disk image через `sfdisk`, `losetup`, `mkfs`, `mount`.
- `src/run_qemu.py` - запуск и smoke-test образа в QEMU.

## Как Идет Сборка

1. `src/main.py` выбирает target (`pi5` или `qemu-virt`).
2. Устанавливаются host-зависимости в Linux build VM. Это зависимости только для сборочной машины.
3. Готовится kernel:
   - либо собирается из Raspberry Pi Linux sources;
   - либо используется готовый `Image` из `LITAINER_PREBUILT_KERNEL_IMAGE`.
4. `NetOSBuildrootBuilder` генерирует Buildroot external tree в `temp/netos-buildroot-external`.
5. Buildroot собирает userspace и архив `rootfs.tar`.
6. Rootfs распаковывается в `container/`.
7. Проект накладывает NetOS branding, network config, device nodes, kernel, OVSDB schema, CLI и agents.
8. `make_image.py` создает raw image: boot-раздел + ext4 rootfs.

Buildroot output кэшируется в `temp/buildroot-output-<target>`, поэтому повторная сборка обычно пересобирает только измененные части.

## Требования К Среде

Полная сборка поддерживается на Linux. На macOS нужна Linux VM, например Lima. Не запускайте `src/main.py` под root: Buildroot не должен собираться от root. Скрипт сам вызывает `sudo` только там, где нужны host-привилегии: `apt`, loop devices, mount и создание файловых систем.

Минимально нужны:

- Python 3.
- `apt`-based Linux VM для автоматической установки host-зависимостей.
- Достаточно места на диске: Buildroot output и image занимают несколько GB.
- `qemu-system-aarch64` для локальной проверки `qemu-virt`.

Docker для сборки не нужен.

## Сборка `qemu-virt`

В Linux VM:

```bash
python3 src/main.py --target qemu-virt
```

Если kernel уже собран и нужно переиспользовать готовый `Image`:

```bash
LITAINER_PREBUILT_KERNEL_IMAGE=/path/to/Image \
NETOS_BUILD_JOBS=3 \
python3 src/main.py --target qemu-virt
```

Проверка запуска:

```bash
python3 src/run_qemu.py --target qemu-virt --host-port 6641 --timeout 300
```

Успешный boot-test должен вывести маркеры:

```text
OVSDB_STARTED
OVS_VSWITCHD_STARTED
NET_AGENT_STARTED
QEMU: ovsdb-server доступен на 127.0.0.1:6641
```

## Ручной Запуск QEMU

Если нужен доступ к serial console:

```bash
qemu-system-aarch64 -M virt -cpu cortex-a72 -m 1024 \
  -kernel temp/rpi_linux/arch/arm64/boot/Image \
  -drive file=qemu-virt.img,format=raw,if=virtio \
  -append "console=ttyAMA0 root=/dev/vda2 rootfstype=ext4 rw rootwait" \
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:6641-127.0.0.1:6640 \
  -device virtio-net-pci,netdev=net0 \
  -serial stdio -display none -no-reboot
```

Если порт `6641` занят, выберите другой host-port.

## Сборка На Этом Mac Через Lima

Фактическая сборка выполнялась в Lima VM `litainer`, в каталоге `~/litainer-netos`. После изменения файлов в macOS-каталоге проекта нужно синхронизировать их в VM или пересоздать VM-копию проекта.

Пример запуска внутри VM:

```bash
limactl shell litainer -- sh -lc 'cd ~/litainer-netos && \
  LITAINER_PREBUILT_KERNEL_IMAGE=/Users/aleksejzaharcenko/work/litainer/temp/rpi_linux/arch/arm64/boot/Image \
  NETOS_BUILD_JOBS=3 \
  python3 src/main.py --target qemu-virt'
```

Копирование готового образа из VM на host:

```bash
limactl copy --backend=scp \
  litainer:/home/aleksejzaharcenko.guest/litainer-netos/qemu-virt.img \
  ./qemu-virt.img
```

## Что Менять В Конфигах

- Добавить/убрать userspace-пакеты: `src/adapters/netos_buildroot.py`, метод `_defconfig()`.
- Поменять branding: `src/netos_branding.py`.
- Поменять target, имя image, boot cmdline или kernel options: `src/targets.py`.
- Поменять init/OVSDB/agents startup: `src/core/container_setup.py`.
- Поменять размер/разметку образа: `src/make_image.py`.
- Поменять OVSDB модель: `src/schema/system.ovsschema`.

Не правьте вручную `temp/buildroot-output-*/.config` как основной источник правды: он будет перегенерирован из `src/adapters/netos_buildroot.py`.

## Полезные Переменные

- `NETOS_VERSION` - версия в `/etc/os-release`; default `0.1.0`.
- `NETOS_BUILD_JOBS` - количество parallel jobs для Buildroot.
- `NETOS_BUILDROOT_VERSION` - версия Buildroot; default `2026.02.1`.
- `NETOS_BUILDROOT_URL` и `NETOS_BUILDROOT_SHA256` - кастомный источник Buildroot.
- `NETOS_OPENVSWITCH_VERSION` - версия Open vSwitch package.
- `LITAINER_KERNEL_BRANCH` - branch Raspberry Pi Linux; default `rpi-6.6.y`.
- `LITAINER_KERNEL_TARBALL_URL` - кастомный tarball kernel sources.
- `LITAINER_PREBUILT_KERNEL_IMAGE` - путь к готовому kernel `Image`, чтобы пропустить сборку kernel.
- `QEMU_BIN` - путь/имя QEMU binary для `src/run_qemu.py`.

## Выходные Артефакты

- `qemu-virt.img` - локальный QEMU image.
- `raspi.img` - Raspberry Pi 5 image.
- `container/` - собранный rootfs перед упаковкой в image.
- `temp/rpi_linux/arch/arm64/boot/Image` - kernel image.
- `temp/buildroot-output-<target>/images/rootfs.tar` - Buildroot rootfs archive.
- `temp/netos-buildroot-external/` - сгенерированный Buildroot external tree.

## Проверки

Компиляция Python-файлов:

```bash
python3 -m compileall src
```

Проверка branding и отсутствия Debian/Ubuntu package manager в rootfs:

```bash
cat container/etc/os-release
test ! -e container/usr/bin/apt
test ! -e container/usr/bin/dpkg
```

Проверка image:

```bash
file qemu-virt.img
python3 src/run_qemu.py --target qemu-virt --host-port 6641 --timeout 300
```

## Что Еще Нужно Для Продакшена

- Пересобрать kernel с нужными OVS datapath/netfilter modules и проверить datapath, а не только OVSDB.
- Проверить `pi5` target на реальном Raspberry Pi 5.
- Ввести release pipeline: pinned source cache/mirror, SBOM, license manifest, checksums, подпись artifacts.
- Продумать обновления: A/B partitions или atomic rootfs update с rollback.
- Разделить immutable OS и persistent config/data partition.
- Настроить secure boot / verified boot для выбранного hardware target.
- Добавить first-boot provisioning и secret management.
- Провести hardening: SSH policy, users, firewall defaults, read-only rootfs option, kernel lockdown.
- Добавить интеграционные тесты агентов, OVSDB schema migration и storage/VM workflows.
