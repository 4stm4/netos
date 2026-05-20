# Запуск в QEMU

## Быстрый старт через run_qemu.py

### qemu-virt (ARM64)

```bash
python3 src/run_qemu.py --target qemu-virt
```

С явным портом SSH и таймаутом ожидания старта:

```bash
python3 src/run_qemu.py --target qemu-virt --host-port 6641 --timeout 300
```

Со smoke-тестом Web UI (дождаться старта и проверить `/health`):

```bash
python3 src/run_qemu.py --target qemu-virt --host-port 6641 --timeout 300 --check-webui
```

### qemu-x86 (x86_64)

```bash
python3 src/run_qemu.py --target qemu-x86
```

```bash
python3 src/run_qemu.py --target qemu-x86 --host-port 6641 --timeout 300 --check-webui
```

---

## Ручной запуск QEMU — ARM64 (qemu-virt)

```bash
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -m 512M \
  -smp 2 \
  -kernel temp/kernel-qemu-virt/Image \
  -append "root=/dev/vda rw console=ttyAMA0 earlycon" \
  -drive file=output/qemu-virt.img,format=raw,if=virtio \
  -netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::6641-:6641,hostfwd=tcp::8080-:8080 \
  -device virtio-net-device,netdev=net0 \
  -nographic
```

### Описание флагов

| Флаг | Описание |
|------|----------|
| `-machine virt` | QEMU виртуальная ARM-машина (нет физического аналога) |
| `-cpu cortex-a72` | Эмуляция процессора Cortex-A72 (как на RPi4) |
| `-m 512M` | Объём ОЗУ для VM |
| `-smp 2` | Число виртуальных CPU |
| `-kernel` | Путь к скомпилированному ядру `Image` |
| `-append` | Параметры командной строки ядра: rootfs на `/dev/vda`, консоль `ttyAMA0` |
| `-drive` | Образ диска в формате RAW, подключается как `virtio-blk` |
| `-netdev user,...` | SLIRP-сеть с пробросом портов с хоста в VM |
| `-device virtio-net-device` | Виртуальный сетевой адаптер |
| `-nographic` | Вывод в терминал (без графического окна), консоль через serial |

---

## Ручной запуск QEMU — x86_64 (qemu-x86)

```bash
qemu-system-x86_64 \
  -machine q35 \
  -cpu qemu64 \
  -m 512M \
  -smp 2 \
  -kernel temp/kernel-qemu-x86/bzImage \
  -append "root=/dev/sda rw console=ttyS0 earlycon" \
  -drive file=output/qemu-x86.img,format=raw,if=ide \
  -netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::6641-:6641,hostfwd=tcp::8080-:8080 \
  -device e1000,netdev=net0 \
  -nographic
```

### Описание флагов

| Флаг | Описание |
|------|----------|
| `-machine q35` | Чипсет Intel Q35 (PCIe, AHCI) |
| `-cpu qemu64` | Базовая x86_64 эмуляция |
| `-kernel` | Путь к `bzImage` (сжатое ядро для x86) |
| `-append` | Rootfs на `/dev/sda`, консоль `ttyS0` |
| `-drive ... if=ide` | Диск через IDE/AHCI |
| `-device e1000` | Эмуляция Intel Gigabit e1000 NIC |

---

## Таблица проброса портов

| Порт хоста | Порт VM | Сервис |
|------------|---------|--------|
| `2222` | `22` | SSH (Dropbear) |
| `6641` | `6641` | OVSDB (Open vSwitch Database) |
| `8080` | `8080` | Web UI (Testum) |

Подключение к SSH:

```bash
ssh -p 2222 root@localhost
```

---

## Smoke-тесты — маркеры в логе консоли

`run_qemu.py --check-webui` ожидает появления следующих строк в serial-выводе:

| Маркер | Значение |
|--------|----------|
| `OVSDB_STARTED` | ovsdb-server успешно запущен |
| `OVS_VSWITCHD_STARTED` | ovs-vswitchd успешно запущен |
| `NET_AGENT_STARTED` | сетевой агент/Nervum запущен |

Если маркеры не появились за `--timeout` секунд — тест считается проваленным.

---

## Подключение к сервисам

### OVSDB (Open vSwitch)

```bash
# Просмотр конфигурации OVS
ovsdb-client dump tcp:localhost:6641

# Или через ovs-vsctl с remote
ovs-vsctl --db=tcp:localhost:6641 show
```

### Web UI (Testum)

```bash
# Проверка health endpoint
curl http://localhost:8080/health

# Открыть в браузере
xdg-open http://localhost:8080
```

### SSH (Dropbear)

```bash
ssh -p 2222 root@localhost
```

---

## Устранение неполадок

**VM не стартует, ошибка "Could not open ... Image"**
Убедитесь, что сборка завершена и файл существует:
```bash
ls -lh output/qemu-virt.img temp/kernel-qemu-virt/Image
```

**Зависание на "Loading initial ramdisk"**
Ядро и образ должны быть собраны для одного target. Не перемешивайте `qemu-virt` ядро с `qemu-x86` образом.

**"Address already in use" при запуске QEMU**
Порт уже занят другим процессом или предыдущим QEMU. Завершите старый процесс:
```bash
pkill -f qemu-system
```

**Консоль не выводит текст**
Проверьте, что в `-append` указан правильный console: `ttyAMA0` для ARM, `ttyS0` для x86.

**Web UI не отвечает на порту 8080**
Проверьте, что Testum запустился — в серийном выводе должна быть строка `NET_AGENT_STARTED`. Если сборка была без Web UI — порт будет недоступен.
