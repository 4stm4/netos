# Сборка netOS

## Требования к среде

- **ОС**: только Linux (Ubuntu 22.04 / Debian 12 рекомендуется)
- **Python**: 3.10 или новее
- **Права**: не запускать от root
- **Место на диске**: минимум 30 ГБ свободного места (Buildroot + toolchain + образы)
- **ОЗУ**: 8 ГБ минимум, 16 ГБ рекомендуется для параллельной сборки

### Зависимости хоста

```bash
sudo apt install -y \
  build-essential git rsync bc cpio unzip wget curl file \
  python3 python3-pip python3-venv \
  libssl-dev libncurses-dev libelf-dev \
  qemu-system-arm qemu-system-x86 qemu-utils
```

### Кросс-компиляторы

| Target | Toolchain |
|--------|-----------|
| pi4, pi5, zero2w, qemu-virt (ARM64) | `aarch64-linux-gnu-` |
| qemu-x86 (x86_64) | `x86_64-linux-gnu-` (или нативный gcc) |

```bash
sudo apt install -y gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu
sudo apt install -y gcc-x86-64-linux-gnu binutils-x86-64-linux-gnu
```

---

## Как работает сборка

Точка входа — `src/main.py`. Пайплайн выполняется последовательно:

1. **Загрузка ядра** — скачивается tarball ядра с kernel.org (mainline) или клонируется ветка `rpi-6.12.y` из `raspberrypi/linux` для RPi-целей
2. **Конфигурация ядра** — применяется `defconfig` для целевой платформы (`bcm2712_defconfig`, `bcm2711_defconfig`, QEMU config)
3. **Компиляция ядра** — `make` с числом потоков по `NETOS_BUILD_JOBS`
4. **Загрузка и настройка Buildroot** — скачивается версия Buildroot (`NETOS_BUILDROOT_VERSION`), подключается external-дерево `netos-buildroot-external/`
5. **Генерация defconfig** — скрипт формирует `_defconfig` по параметрам профиля и переменным окружения; вписываются все `BR2_PACKAGE_*=y`
6. **Сборка rootfs через Buildroot** — `make` собирает все пакеты, на выходе rootfs tar-архив
7. **Извлечение rootfs и overlay** — rootfs распаковывается, поверх накладываются файлы overlay: сетевые конфиги, init-скрипты, Web UI (Testum), Nervum
8. **Создание образа** — формируется финальный `.img` нужного размера (ext4 rootfs + FAT boot-раздел для RPi)

Промежуточные результаты кешируются в `temp/buildroot-output-<target>/` — повторная сборка не пересобирает уже собранные пакеты.

---

## Команды сборки

### qemu-virt (ARM64, mainline kernel)

```bash
python3 src/main.py --target qemu-virt
```

### qemu-x86 (x86_64, mainline kernel)

```bash
python3 src/main.py --target qemu-x86
```

### pi5 (BCM2712)

```bash
python3 src/main.py --target pi5
```

### pi4 (BCM2711)

```bash
python3 src/main.py --target pi4
```

### zero2w (BCM2710, WiFi)

```bash
python3 src/main.py --target zero2w
```

### С профилем

```bash
python3 src/main.py --target qemu-virt --profile profiles/myconfig.yaml
```

### С дополнительными пакетами из файла

```bash
python3 src/main.py --target pi4 --packages-file extra.txt
```

---

## Профили YAML

Профиль — YAML-файл, который описывает всю конфигурацию сборки. Позволяет зафиксировать параметры и воспроизводить сборку без ручного задания переменных окружения.

### Полная структура профиля с комментариями

```yaml
name: default            # Имя профиля (произвольное)
target: qemu-virt        # Target: qemu-virt | qemu-x86 | pi5 | pi4 | zero2w

branding:
  name: 4stm4 netOS      # Отображаемое имя системы
  version: 0.1.0         # Версия образа (попадает в /etc/netos-release)
  hostname: 4stm4-netos  # hostname системы

network:
  eth0:
    mode: dhcp            # dhcp | static
    address: ''           # IP-адрес при mode: static, например 192.168.1.10/24
    gateway: ''           # Шлюз при mode: static
    dns: ''               # DNS-сервер при mode: static
  wifi:
    country: US           # Код страны Wi-Fi (ISO 3166-1 alpha-2)
    ssid: ''              # SSID сети (только для zero2w)
    psk: ''               # Пароль Wi-Fi
    bootstrap: true       # Поднять Wi-Fi при первом старте

packages:
  enabled: []             # Список ключей из packages.yaml, например: [tcpdump, htop]
  custom: []              # Произвольные BR2_PACKAGE_*=y строки, например: [BR2_PACKAGE_STRACE=y]

webui:
  source: git             # git | local
  git_url: https://github.com/4stm4/testum.git
  git_ref: main           # Ветка или тег
  source_dir: ''          # Локальный путь (если source: local)
  port: 8080              # Порт Web UI внутри образа
  admin_username: admin
  admin_password: ''      # Пароль admin-пользователя Web UI

image:
  size_mb: 512            # Полный размер образа в МБ
  boot_mb: 64             # Размер FAT boot-раздела в МБ (только RPi)
```

### Использование флага `--profile`

```bash
python3 src/main.py --target pi4 --profile profiles/production.yaml
```

Параметры профиля имеют приоритет над значениями по умолчанию. Переменные окружения `NETOS_*`, заданные явно в shell, могут переопределять профиль.

---

## Файл дополнительных пакетов (`--packages-file`)

Текстовый файл — одна строка `BR2_PACKAGE_*=y` на пакет:

```
BR2_PACKAGE_TCPDUMP=y
BR2_PACKAGE_HTOP=y
BR2_PACKAGE_STRACE=y
```

```bash
python3 src/main.py --target qemu-virt --packages-file extra.txt
```

Строки из файла добавляются в defconfig поверх пакетов из профиля.

---

## Удалённая сборка на rpi4-codex

Сборочный сервер: `192.168.88.51`, пользователь `codex`, рабочая директория `/mnt/build-ssd/litainer-build/litainer`.

### Синхронизация исходников

```bash
rsync -av --exclude='temp/' --exclude='*.img' --exclude='output/' \
  /path/to/netos/ codex@192.168.88.51:/mnt/build-ssd/litainer-build/litainer/
```

### Запуск сборки по SSH

```bash
ssh codex@192.168.88.51 \
  "cd /mnt/build-ssd/litainer-build/litainer && python3 src/main.py --target pi5"
```

### Получение образа обратно

```bash
rsync -av \
  codex@192.168.88.51:/mnt/build-ssd/litainer-build/litainer/output/ \
  ./output/
```

---

## Инкрементальная пересборка

Buildroot-кеш хранится в `temp/buildroot-output-<target>/`. При повторном запуске Buildroot пересобирает только изменившиеся компоненты.

Полная очистка кеша для конкретного target:

```bash
rm -rf temp/buildroot-output-qemu-virt/
```

Пересборка только rootfs без пересборки пакетов:

```bash
make -C temp/buildroot-output-qemu-virt/ rootfs-ext2-rebuild
```

---

## Выходные артефакты

После успешной сборки файлы появляются в `output/`:

| Файл | Описание |
|------|----------|
| `output/qemu-virt.img` | Образ для QEMU ARM64 |
| `output/qemu-x86.img` | Образ для QEMU x86_64 |
| `output/raspi.img` | Образ для RPi (pi4, pi5, zero2w) |

Вспомогательные директории:

| Директория | Описание |
|------------|----------|
| `temp/buildroot-output-<target>/` | Buildroot build cache (пакеты, toolchain) |
| `temp/kernel-<target>/` | Скомпилированное ядро и модули |
| `container/` | Вспомогательные файлы для контейнерного деплоя (если применимо) |
