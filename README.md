# netOS

netOS - это собираемая из исходников ARM64 appliance OS для сетевого/виртуализационного узла. Проект собирает Linux kernel, минимальный userspace через Buildroot, Open vSwitch/OVSDB, системную OVSDB-схему, агенты управления и готовый raw-образ диска.

Целевая система не является Ubuntu/Debian rootfs. Внутри target rootfs нет `apt`, `dpkg`, `mmdebstrap`, `debootstrap` и Docker-зависимостей. Ubuntu/Linux VM используется только как среда сборки на хосте.

## Текущий Статус

- Рабочий локальный target: `qemu-virt`.
- Собран и проверен образ: `qemu-virt.img`.
- Размер raw-образа по умолчанию: `qemu-virt` - 512 MB, `pi5`/`zero2w` - 1024 MB.
- Внутри rootfs branding: `NAME="netOS"`, `ID=netos`.
- QEMU boot-test проходит: rootfs монтируется, сеть поднимается, `dropbear` стартует, `ovsdb-server` доступен через host-forward.
- Для полноценного Open vSwitch datapath еще нужно пересобрать kernel с поддержкой `ovs_datapath`; сейчас OVSDB и `ovs-vswitchd` стартуют, но kernel datapath в текущем prebuilt kernel отсутствует.

## Что Собирается

- ARM64 Linux kernel.
- Buildroot rootfs `netOS`.
- Open vSwitch userspace: `ovsdb-server`, `ovs-vswitchd`, CLI tools и Python-модули.
- `/etc/os-release`, `/usr/lib/os-release`, hostname, issue и базовые системные конфиги.
- OVSDB schema: `src/schema/system.ovsschema`.
- Management agents:
  - `net_agent.py` - сетевые интерфейсы, bridge/state, hostname/timezone/log level.
  - `storage_agent.py` - iSCSI login и mount workflow.
  - `vm_agent.py` - управление VM-процессами и cgroup assignment.
  - `stat_agent.py` - телеметрия.
- Testum Web UI offline bundle: `/opt/testum`, `/etc/netos/webui.env`, `/usr/local/sbin/netos-webui-service`, `/etc/init.d/S98testum`.
- Init hook `S99netos`, который поднимает OVSDB, Open vSwitch, агентов и watchdog loop.
- Raw disk image с двумя разделами: FAT boot и ext4 rootfs.

## Targets

- `qemu-virt` - generic ARM64 QEMU `virt` image для локальной проверки. Output: `qemu-virt.img`.
- `pi5` - Raspberry Pi 5 / BCM2712 hardware image. Output: `raspi.img`.
- `zero2w` - Raspberry Pi Zero 2 W / BCM2710 ARM64 hardware image. Output: `raspi-zero2w.img`.

Размеры образов по умолчанию:

| Target | Image | Boot partition | Rootfs partition |
|---|---:|---:|---:|
| `qemu-virt` | 512 MB | 64 MB | ~447 MB |
| `pi5` | 1024 MB | 256 MB | ~767 MB |
| `zero2w` | 1024 MB | 256 MB | ~767 MB |

`qemu-virt` проверен локально. Hardware targets `pi5` и `zero2w` требуют проверки на реальном устройстве.

## Основные Файлы

- `src/main.py` - главный entrypoint сборки.
- `src/targets.py` - target profiles: kernel defconfig, имя образа, boot cmdline, QEMU machine.
- `src/netos_branding.py` - имя ОС, `ID`, hostname, версия.
- `src/adapters/netos_buildroot.py` - Buildroot version, external tree, defconfig, overlay, пакет Open vSwitch.
- `src/adapters/linux_kernel.py` - подготовка/сборка kernel или подключение prebuilt `Image`.
- `src/core/container_setup.py` - финальная настройка rootfs, `/etc/os-release`, init-скрипты, offline Web UI bundle, OVSDB schema и агенты.
- `src/make_image.py` - создание raw disk image через `sfdisk`, `losetup`, `mkfs`, `mount`.
- `src/run_qemu.py` - запуск и smoke-test образа в QEMU.

## Как Идет Сборка

1. `src/main.py` выбирает target (`pi5`, `zero2w` или `qemu-virt`).
2. Устанавливаются host-зависимости в Linux build VM. Это зависимости только для сборочной машины.
3. Готовится kernel:
   - либо собирается из Raspberry Pi Linux sources;
   - либо используется готовый `Image` из `NETOS_PREBUILT_KERNEL_IMAGE`.
4. `NetOSBuildrootBuilder` генерирует Buildroot external tree в `temp/netos-buildroot-external`.
5. Buildroot собирает userspace и архив `rootfs.tar`.
6. Rootfs распаковывается в `container/`.
7. Проект накладывает netOS branding, network config, device nodes, kernel, offline Testum Web UI, OVSDB schema, CLI и agents.
8. `make_image.py` создает raw image: boot-раздел + ext4 rootfs.

Buildroot output кэшируется в `temp/buildroot-output-<target>`, поэтому повторная сборка обычно пересобирает только измененные части.

## Сборка Raspberry Pi

Raspberry Pi 5:

```bash
python3 src/main.py --target pi5
```

Raspberry Pi Zero 2 W:

```bash
python3 src/main.py --target zero2w
```

Для `zero2w` сборка дополнительно кладет на boot-раздел firmware-файлы Raspberry Pi (`bootcode.bin`, `start.elf`, `fixup.dat`) и включает Wi-Fi пакеты. Если нужен headless-доступ по Wi-Fi, задайте параметры сети на этапе сборки:

```bash
NETOS_WIFI_COUNTRY=US \
NETOS_WIFI_SSID='my-wifi' \
NETOS_WIFI_PSK='my-password' \
python3 src/main.py --target zero2w
```

Можно не пересобирать образ ради Wi-Fi: после записи SD-карты положите на FAT boot-раздел файл `wpa_supplicant.conf` или `netos-wifi.conf`. При первом boot `/etc/init.d/S39wifi` скопирует его в `/etc/wpa_supplicant.conf`, поднимет `wlan0` и запустит DHCP.

Минимальный `wpa_supplicant.conf`:

```conf
ctrl_interface=/var/run/wpa_supplicant
update_config=1
country=US

network={
    ssid="my-wifi"
    psk="my-password"
}
```

Если firmware уже скачан локально, можно использовать его вместо загрузки из GitHub:

```bash
NETOS_RPI_FIRMWARE_DIR=/path/to/raspberrypi-firmware/boot \
python3 src/main.py --target zero2w
```

## Требования К Среде

Полная сборка поддерживается на Linux. На macOS нужна Linux VM, например Lima. Не запускайте `src/main.py` под root: Buildroot не должен собираться от root. Скрипт сам вызывает `sudo` только там, где нужны host-привилегии: `apt`, loop devices, mount и создание файловых систем.

Минимально нужны:

- Python 3.
- `apt`-based Linux VM для автоматической установки host-зависимостей.
- Достаточно места на диске: Buildroot output и image занимают несколько GB.
- `qemu-system-aarch64` для локальной проверки `qemu-virt`.

Docker для сборки не нужен.

## Пакетный Менеджер

Внутри netOS нет runtime package manager: `apt`, `dpkg`, `apk`, `opkg` и `rpm` намеренно не входят в target rootfs. Это не Ubuntu/Alpine, а appliance image на Buildroot.

Пакеты добавляются в сборку через `src/adapters/netos_buildroot.py`, метод `_defconfig()`, после чего образ пересобирается:

```bash
python3 src/main.py --target qemu-virt
```

Buildroot сам скачает, сконфигурирует и встроит выбранные пакеты в rootfs. На уже запущенной netOS устанавливать системные пакеты штатным способом нельзя; для изменений нужно менять конфиг сборки и выпускать новый image.

## Сборка `qemu-virt`

В Linux VM:

```bash
python3 src/main.py --target qemu-virt
```

Если kernel уже собран и нужно переиспользовать готовый `Image`:

```bash
NETOS_PREBUILT_KERNEL_IMAGE=/path/to/Image \
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

С проверкой Web UI:

```bash
python3 src/run_qemu.py --target qemu-virt --host-port 6641 --check-webui
```

## Web UI Панель

В сборку добавлен offline bundle для Testum Web UI без Docker. Исходники панели запекаются в rootfs на этапе сборки, поэтому на первом boot netOS не скачивает `install.sh` и не делает `git clone`.

Так как netOS использует BusyBox init, а не systemd, автозапуск сделан через SysV init-script:

- приложение: `/opt/testum`;
- конфиг: `/etc/netos/webui.env`;
- сервисный bootstrap: `/usr/local/sbin/netos-webui-service`;
- автозапуск: `/etc/init.d/S98testum`;
- SQLite база по умолчанию: `/opt/testum/testum.db`;
- порт по умолчанию: `8080`.

Дефолтные значения уже зашиты в сборку:

| Переменная | Значение |
|---|---|
| `NETOS_WEBUI_EMBED` | `1` |
| `NETOS_WEBUI_GIT_URL` | `https://github.com/4stm4/testum.git` |
| `NETOS_WEBUI_GIT_REF` | `main` |
| `NETOS_WEBUI_DATABASE_URL` | `sqlite:////opt/testum/testum.db` |
| `NETOS_WEBUI_PIP_MODE` | `never` |
| `NETOS_WEBUI_APP_MODULE` | `app.main:app` |
| `NETOS_WEBUI_PYTHONPATH` | `src` |
| `NETOS_WEBUI_START_CMD` | `python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${TESTUM_PORT:-8080}` |
| `NETOS_WEBUI_MIGRATE_CMD` | `python3 -m alembic upgrade head` |
| `NETOS_WEBUI_HEALTH_PATH` | `/health` |

Docker, systemd, Node.js/npm и frontend build для Testum не нужны. Статика уже хранится в репозитории: `src/ports/web/static/`.

Есть два основных способа запечь исходники панели в образ.

1. По умолчанию сборщик клонирует Testum на этапе сборки:

```bash
NETOS_WEBUI_PORT=8080 \
python3 src/main.py --target qemu-virt
```

Внутри готового образа `/etc/netos/webui.env` получит:

```text
TESTUM_PRELOADED='1'
TESTUM_INSTALL_URL=''
TESTUM_GIT_URL=''
TESTUM_PIP_MODE='never'
```

2. Для полностью контролируемой offline-сборки укажите локальную директорию Testum:

```bash
NETOS_WEBUI_SOURCE_DIR=/path/to/testum \
python3 src/main.py --target qemu-virt
```

При копировании из source удаляются `.git`, `.venv`, cache, bytecode, `node_modules` и dev database файлы. Дополнительно в `/opt/testum/.python` запекаются Python-пакеты, которых нет в Buildroot, сейчас это `pyjobkit==1.0.0` и `croniter==6.2.2`.

Если `NETOS_WEBUI_ADMIN_PASSWORD` не задан, пароль будет сгенерирован на первом boot и сохранен в `/var/lib/testum/runtime.env`. Там же генерируются `SECRET_KEY`, `FERNET_KEY`, `ADMIN_PASSWORD`, `DATABASE_URL` и другие runtime-переменные.

Для нестандартного приложения задайте:

- `NETOS_WEBUI_EMBED=0` - вернуться к runtime download через `install.sh` или git.
- `NETOS_WEBUI_EMBED_VENDOR_PACKAGES` - список Python-пакетов, которые нужно положить в `/opt/testum/.python`.
- `NETOS_WEBUI_PIP_MODE=auto` - разрешить target-side `pip install -r requirements.txt` при первом boot.
- `NETOS_WEBUI_DATABASE_URL` - SQLite/PostgreSQL DSN.
- `NETOS_WEBUI_START_CMD` - точная команда запуска.
- `NETOS_WEBUI_MIGRATE_CMD` - точная команда миграций.
- `NETOS_WEBUI_APP_MODULE` - ASGI module для `uvicorn`, например `app.main:app`.
- `NETOS_WEBUI_PYTHONPATH` - Python import path относительно `/opt/testum`, по умолчанию `src`.

Smoke-test панели:

```bash
curl -sf http://127.0.0.1:8080/health
```

Ожидаемый ответ:

```json
{"status":"healthy", "...": "..."}
```

## Ручной Запуск QEMU

Если нужен доступ к serial console:

```bash
qemu-system-aarch64 -M virt -cpu cortex-a72 -m 1024 \
  -kernel temp/rpi_linux/arch/arm64/boot/Image \
  -drive file=qemu-virt.img,format=raw,if=virtio \
  -append "console=ttyAMA0 root=/dev/vda2 rootfstype=ext4 rw rootwait" \
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:6641-127.0.0.1:6640,hostfwd=tcp:127.0.0.1:8080-127.0.0.1:8080 \
  -device virtio-net-pci,netdev=net0 \
  -serial stdio -display none -no-reboot
```

Если порт `6641` или `8080` занят, выберите другой host-port.

## Сборка На Remote Builder

Полная сборка выполняется на Linux. Для этого можно использовать отдельную Raspberry Pi или Linux VM с SSD.

Пример для remote builder:

```bash
ssh rpi4-codex
cd /mnt/build-ssd/netos-build/netos
NETOS_BUILD_JOBS=2 python3 src/main.py --target zero2w
```

Если нужна Lima VM на macOS, создайте отдельный instance, синхронизируйте проект внутрь VM и запускайте те же команды сборки уже в Linux-окружении.

Копирование готового образа с remote builder на host:

```bash
scp rpi4-codex:/mnt/build-ssd/netos-build/netos/raspi-zero2w.img .
```

## Что Менять В Конфигах

- Добавить/убрать userspace-пакеты: `src/adapters/netos_buildroot.py`, метод `_defconfig()`.
- Поменять branding: `src/netos_branding.py`.
- Поменять target, имя image, boot cmdline или kernel options: `src/targets.py`.
- Поменять init/offline Web UI/OVSDB/agents startup: `src/core/container_setup.py`.
- Поменять размер/разметку образа: `src/make_image.py`.
- Поменять OVSDB модель: `src/schema/system.ovsschema`.

Не правьте вручную `temp/buildroot-output-*/.config` как основной источник правды: он будет перегенерирован из `src/adapters/netos_buildroot.py`.

## Полезные Переменные

- `NETOS_VERSION` - версия в `/etc/os-release`; default `0.1.0`.
- `NETOS_BUILD_JOBS` - количество parallel jobs для kernel и Buildroot.
- `NETOS_BUILDROOT_VERSION` - версия Buildroot; default `2026.02.1`.
- `NETOS_BUILDROOT_URL` и `NETOS_BUILDROOT_SHA256` - кастомный источник Buildroot.
- `NETOS_OPENVSWITCH_VERSION` - версия Open vSwitch package.
- `NETOS_KERNEL_BRANCH` - branch Raspberry Pi Linux; default `rpi-6.6.y`.
- `NETOS_KERNEL_TARBALL_URL` - кастомный tarball kernel sources.
- `NETOS_PREBUILT_KERNEL_IMAGE` - путь к готовому kernel `Image`, чтобы пропустить сборку kernel.
- `NETOS_RPI_FIRMWARE_BASE_URL` - base URL для Raspberry Pi boot firmware; default `https://raw.githubusercontent.com/raspberrypi/firmware/master/boot`.
- `NETOS_RPI_FIRMWARE_DIR` - локальный каталог с Raspberry Pi boot firmware вместо скачивания.
- Старые aliases `LITAINER_*` пока поддерживаются для совместимости, но новые команды должны использовать `NETOS_*`.
- `QEMU_BIN` - путь/имя QEMU binary для `src/run_qemu.py`.
- `NETOS_IMAGE_SIZE_MB` - override размера raw image в MB.
- `NETOS_BOOT_SIZE_MB` - override размера boot-раздела в MB.
- `NETOS_ETH0_ADDRESS`, `NETOS_ETH0_NETMASK`, `NETOS_ETH0_GATEWAY`, `NETOS_ETH0_DNS` - статическая сеть для `eth0`; если `NETOS_ETH0_ADDRESS` не задан, используется DHCP.
- `NETOS_WIFI_COUNTRY`, `NETOS_WIFI_SSID`, `NETOS_WIFI_PSK` - Wi-Fi provisioning для `wlan0`, полезно для `zero2w`.
- `NETOS_WIFI_BOOTSTRAP` - включает `/etc/init.d/S39wifi`, который может взять `wpa_supplicant.conf` или `netos-wifi.conf` с boot-раздела; default `1`.
- `NETOS_WEBUI_ENABLED` - включает/выключает Web UI bootstrap; default `1`.
- `NETOS_WEBUI_EMBED` - запекать Testum source в образ; default `1`.
- `NETOS_WEBUI_PORT` - порт Web UI; default `8080`.
- `NETOS_WEBUI_DATA_DIR` - каталог установки; default `/opt/testum`.
- `NETOS_WEBUI_INSTALL_URL` - URL upstream `install.sh`, используется только если `NETOS_WEBUI_EMBED=0`.
- `NETOS_WEBUI_GIT_URL` и `NETOS_WEBUI_GIT_REF` - git source для build-time embed или runtime fallback.
- `NETOS_WEBUI_SOURCE_DIR` - локальная директория, которую нужно встроить в rootfs вместо git clone.
- `NETOS_WEBUI_EMBED_VENDOR_PACKAGES` - pure-Python пакеты для `/opt/testum/.python`; default `pyjobkit==1.0.0 croniter==6.2.2`.
- `NETOS_WEBUI_PIP_MODE` - `never` по умолчанию; `auto` разрешает pip/venv на первом boot.
- `NETOS_WEBUI_DATABASE_URL` - default `sqlite:////opt/testum/testum.db`.
- `NETOS_WEBUI_APP_ENV` - default `production`.
- `NETOS_WEBUI_ADMIN_USERNAME` - default `admin`.
- `NETOS_WEBUI_ADMIN_PASSWORD` - начальный пароль администратора.
- `NETOS_WEBUI_START_CMD`, `NETOS_WEBUI_MIGRATE_CMD`, `NETOS_WEBUI_APP_MODULE` - override для запуска/миграций.
- `NETOS_WEBUI_PYTHONPATH` - Python import path для панели; default `src`.
- `NETOS_WEBUI_HEALTH_PATH` - HTTP health path для smoke-test; default `/health`.

## Выходные Артефакты

- `qemu-virt.img` - локальный QEMU image.
- `raspi.img` - Raspberry Pi 5 image.
- `raspi-zero2w.img` - Raspberry Pi Zero 2 W image.
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
python3 src/run_qemu.py --target qemu-virt --host-port 6641 --timeout 300 --check-webui
```

## Что Еще Нужно Для Продакшена

- Пересобрать kernel с нужными OVS datapath/netfilter modules и проверить datapath, а не только OVSDB.
- Проверить Testum Web UI в полном netOS boot после rebuild: миграции, startup command и `/health`.
- Проверить `pi5` target на реальном Raspberry Pi 5.
- Проверить `zero2w` target на реальном Raspberry Pi Zero 2 W.
- Ввести release pipeline: pinned source cache/mirror, SBOM, license manifest, checksums, подпись artifacts.
- Продумать обновления: A/B partitions или atomic rootfs update с rollback.
- Разделить immutable OS и persistent config/data partition.
- Настроить secure boot / verified boot для выбранного hardware target.
- Добавить first-boot provisioning и secret management.
- Провести hardening: SSH policy, users, firewall defaults, read-only rootfs option, kernel lockdown.
- Добавить интеграционные тесты агентов, OVSDB schema migration и storage/VM workflows.
