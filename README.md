# netOS

Сборочная из исходников ARM64/x86_64 appliance OS для сетевого и виртуализационного узла.

Внутри: Linux kernel, минимальный userspace (Buildroot), Open vSwitch / OVSDB, управляющие агенты, Web UI (Testum) и SDN-контроллер (Nervum). Собирается в готовый raw disk image.

**Это не Ubuntu/Debian rootfs.** В target-системе нет `apt`, `dpkg`, `docker`. Buildroot управляет всем userspace.

## Быстрый старт

```bash
# Собрать образ для QEMU (ARM64)
python3 src/main.py --target qemu-virt

# Запустить и проверить
python3 src/run_qemu.py --target qemu-virt
```

Сборка занимает 30–90 минут при первом запуске; последующие инкрементальны.

## Targets

| Target | Архитектура | Ядро | Образ | Размер |
|---|---|---|---|---|
| `qemu-virt` | ARM64 | mainline 6.12 | `qemu-virt.img` | 512 MB |
| `qemu-x86` | x86\_64 | mainline 6.12 | `qemu-x86.img` | 512 MB |
| `pi5` | ARM64 | rpi-6.12.y | `raspi.img` | 1024 MB |
| `pi4` | ARM64 | rpi-6.12.y | `raspi-pi4.img` | 1024 MB |
| `zero2w` | ARM64 | rpi-6.12.y | `raspi-zero2w.img` | 1024 MB |

## Web-конфигуратор

Браузерный интерфейс для настройки и запуска сборок:

```bash
python3 src/configurator/serve.py --host 0.0.0.0 --port 5173
```

Открыть: `http://localhost:5173`

## Документация

- [Сборка](docs/build.md) — требования, команды, профили, переменные окружения
- [Targets](docs/targets.md) — описание каждого target, ядра, архитектуры
- [QEMU](docs/qemu.md) — запуск в QEMU, port forwarding, x86 vs ARM
- [Конфигуратор](docs/configurator.md) — web-интерфейс, шаги мастера, профили
- [Пакеты](docs/packages.md) — добавление пакетов, presets, кастомные BR2_PACKAGE
- [Сеть](docs/networking.md) — eth0, Wi-Fi, Open vSwitch / OVSDB
- [Переменные окружения](docs/env-reference.md) — полный справочник NETOS_*

## Требования к среде сборки

- Linux (macOS — только через Lima VM или remote builder)
- Python 3.10+
- Не запускать под root — `sudo` вызывается автоматически только для `mount`/`losetup`
- ~10 GB свободного места на диске

## Лицензия

Смотри [LICENSE](LICENSE).
