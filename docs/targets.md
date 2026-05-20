# Targets

## Сводная таблица

| Target | Архитектура | Ядро | Версия ядра | QEMU | WiFi |
|--------|-------------|------|-------------|------|------|
| `qemu-virt` | ARM64 (AArch64) | mainline kernel.org | 6.12.27 | да (machine=virt) | нет |
| `qemu-x86` | x86_64 | mainline kernel.org | 6.12.27 | да (machine=q35) | нет |
| `pi5` | ARM64 (BCM2712) | raspberrypi/linux | rpi-6.12.y | нет | нет (PCIe) |
| `pi4` | ARM64 (BCM2711) | raspberrypi/linux | rpi-6.12.y | нет | нет |
| `zero2w` | ARM64 (BCM2710) | raspberrypi/linux | rpi-6.12.y | нет | да |

---

## qemu-virt

**Архитектура**: ARM64 (AArch64)
**Ядро**: mainline kernel.org, версия `6.12.27` (задаётся `NETOS_MAINLINE_KERNEL_VERSION`)
**QEMU machine**: `virt`
**QEMU CPU**: `cortex-a72`
**Defconfig**: конфиг QEMU virt для ARM64

### Особенности

- Основной target для разработки и тестирования — не требует физического железа
- Поддерживает проброс портов через QEMU SLIRP networking
- Поддерживает smoke-тесты через `run_qemu.py --check-webui`

### Размеры образа по умолчанию

| Параметр | Значение |
|----------|----------|
| Размер образа | 512 МБ |
| Boot-раздел | не используется (нет FAT) |

### Команда сборки

```bash
python3 src/main.py --target qemu-virt
```

---

## qemu-x86

**Архитектура**: x86_64
**Ядро**: mainline kernel.org, версия `6.12.27`
**QEMU machine**: `q35`
**QEMU CPU**: `qemu64`
**Defconfig**: конфиг QEMU x86_64

### Особенности

- Target для тестирования на x86_64-совместимых машинах и CI
- Использует QEMU Q35 chipset (PCIe, AHCI)
- Нативная компиляция ядра возможна на x86_64-хосте

### Размеры образа по умолчанию

| Параметр | Значение |
|----------|----------|
| Размер образа | 512 МБ |
| Boot-раздел | не используется |

### Команда сборки

```bash
python3 src/main.py --target qemu-x86
```

---

## pi5

**Архитектура**: ARM64 (BCM2712, Cortex-A76)
**Ядро**: `raspberrypi/linux`, ветка `rpi-6.12.y`
**Defconfig**: `bcm2712_defconfig`
**Kernel image**: `kernel_2712.img`

### Особенности

- Поддержка PCIe Gen 3 (NVMe, USB 3.0 расширители)
- Требует RPi 5 firmware в `NETOS_RPI_FIRMWARE_DIR`
- Образ записывается на SD-карту или USB-накопитель командой `dd`

### Размеры образа по умолчанию

| Параметр | Значение |
|----------|----------|
| Размер образа | 512 МБ |
| Boot-раздел (FAT) | 64 МБ |

### Команда сборки

```bash
python3 src/main.py --target pi5
```

### Запись образа на SD-карту

```bash
sudo dd if=output/raspi.img of=/dev/sdX bs=4M status=progress conv=fsync
```

---

## pi4

**Архитектура**: ARM64 (BCM2711, Cortex-A72)
**Ядро**: `raspberrypi/linux`, ветка `rpi-6.12.y`
**Defconfig**: `bcm2711_defconfig`
**Kernel image**: `kernel8.img`

### Особенности

- Наиболее протестированный физический target
- Поддержка USB 3.0, Gigabit Ethernet
- Может использоваться как сборочный сервер (см. rpi4-codex в `docs/build.md`)

### Размеры образа по умолчанию

| Параметр | Значение |
|----------|----------|
| Размер образа | 512 МБ |
| Boot-раздел (FAT) | 64 МБ |

### Команда сборки

```bash
python3 src/main.py --target pi4
```

### Запись образа на SD-карту

```bash
sudo dd if=output/raspi.img of=/dev/sdX bs=4M status=progress conv=fsync
```

---

## zero2w

**Архитектура**: ARM64 (BCM2710, Cortex-A53)
**Ядро**: `raspberrypi/linux`, ветка `rpi-6.12.y`
**Defconfig**: `bcm2711_defconfig`
**Kernel image**: `kernel8.img`

### Особенности

- Единственный target с поддержкой Wi-Fi (встроенный Cypress CYW43438)
- Компактный форм-фактор (Zero 2 W)
- Wi-Fi настраивается через профиль (`network.wifi`) или переменные `NETOS_WIFI_*`
- При `wifi.bootstrap: true` Wi-Fi поднимается автоматически при первом старте

### Настройка Wi-Fi в профиле

```yaml
network:
  wifi:
    country: RU
    ssid: MyNetwork
    psk: mypassword
    bootstrap: true
```

### Размеры образа по умолчанию

| Параметр | Значение |
|----------|----------|
| Размер образа | 512 МБ |
| Boot-раздел (FAT) | 64 МБ |

### Команда сборки

```bash
python3 src/main.py --target zero2w
```

### Запись образа на SD-карту

```bash
sudo dd if=output/raspi.img of=/dev/sdX bs=4M status=progress conv=fsync
```
