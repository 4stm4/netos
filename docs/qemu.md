# Запуск в QEMU

## Три варианта образов

| Образ | Файлы | Размер | Загрузка |
|-------|-------|--------|----------|
| **qemu-x86** (полный) | `qemu-x86.img` / `qemu-x86.qcow2` | ~200–500 МБ | ~30 с |
| **qemu-x86-mini** (initramfs) | `rootfs.cpio.gz` | ~0.7 МБ | ~25 с |
| **qemu-virt** (ARM64) | `qemu-virt.img` | ~300–500 МБ | ~60 с |

---

## Запуск

### Через run_qemu.py (рекомендуется)

```bash
# qemu-x86 (x86_64, полный образ)
python3 src/run_qemu.py --target qemu-x86

# qemu-virt (ARM64)
python3 src/run_qemu.py --target qemu-virt

# Увеличить таймаут ожидания старта
python3 src/run_qemu.py --target qemu-x86 --timeout 120 --skip-tcp-check
```

Скрипт автоматически пробрасывает порты:
- `localhost:2222` → SSH внутри VM
- `localhost:6640` → OVSDB
- `localhost:8080` → Web UI

---

### Вручную — полный образ qemu-x86

```bash
KERNEL=temp/mainline_linux/arch/x86/boot/bzImage
IMAGE=qemu-x86.qcow2   # или qemu-x86.img

sudo qemu-system-x86_64 \
  -M q35 -cpu qemu64 -m 512 -smp 2 \
  -kernel $KERNEL \
  -drive file=$IMAGE,format=qcow2,if=virtio \
  -append "console=ttyS0 root=/dev/vda2 rootfstype=ext4 rw rootwait" \
  -netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::8080-:8080 \
  -device virtio-net-pci,netdev=net0 \
  -nographic -no-reboot
```

> Если образ в формате `raw` (`.img`) — замените `format=qcow2` на `format=raw`.

---

### Вручную — мини initramfs (qemu-x86-mini)

Без диска, загружается полностью в ОЗУ за ~25 с:

```bash
KERNEL=temp/mainline_linux/arch/x86/boot/bzImage
INITRD=path/to/rootfs.cpio.gz

sudo qemu-system-x86_64 \
  -M q35 -cpu qemu64 -m 256 \
  -kernel $KERNEL \
  -initrd $INITRD \
  -append "console=ttyS0 init=/init" \
  -nographic -no-reboot
```

---

### Вручную — ARM64 (qemu-virt)

```bash
KERNEL=temp/mainline_linux/arch/arm64/boot/Image
IMAGE=qemu-virt.qcow2

qemu-system-aarch64 \
  -M virt -cpu cortex-a72 -m 512 -smp 2 \
  -kernel $KERNEL \
  -drive file=$IMAGE,format=qcow2,if=virtio \
  -append "console=ttyAMA0 root=/dev/vda2 rootfstype=ext4 rw rootwait" \
  -netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::8080-:8080 \
  -device virtio-net-pci,netdev=net0 \
  -nographic -no-reboot
```

---

## Вход в систему

### Серийная консоль (прямо в терминале)

После загрузки в том же окне появится приглашение входа:

```
netos login: root
Password:         ← пустой пароль, просто Enter
# 
```

---

### SSH (после загрузки)

```bash
ssh -p 2222 -o StrictHostKeyChecking=no root@localhost
```

> SSH работает только если в образе установлен Dropbear (`BR2_PACKAGE_DROPBEAR=y`).  
> В мини initramfs SSH нет — только консоль.

---

## Выход

### Из консоли внутри VM

```bash
poweroff       # мягкое выключение (ACPI)
# или
halt -f        # принудительно
```

---

### Из терминала снаружи (если QEMU завис или нет доступа к консоли)

**Комбинация клавиш QEMU:**

```
Ctrl+A  затем  X
```

Нажать `Ctrl+A`, отпустить, затем нажать `X` — QEMU завершится немедленно.

> Другие полезные комбинации:
> | Комбинация | Действие |
> |------------|----------|
> | `Ctrl+A X` | Выход из QEMU |
> | `Ctrl+A H` | Справка по комбинациям |
> | `Ctrl+A C` | Открыть QEMU monitor (для отладки) |

**Или через kill:**

```bash
pkill -f qemu-system-x86_64
# или
pkill -f qemu-system-aarch64
```

---

## Таблица портов (при запуске через run_qemu.py)

| Хост | VM | Сервис |
|------|----|--------|
| `localhost:2222` | `22` | SSH (Dropbear) |
| `localhost:6640` | `6640` | OVSDB |
| `localhost:8080` | `8080` | Web UI |

---

## Устранение неполадок

**Нет вывода в консоли после запуска**
→ Ядро загрузилось, но `console=` не совпадает. Для x86 должно быть `ttyS0`, для ARM — `ttyAMA0`.

**Kernel panic: not syncing: VFS: Unable to mount root fs**
→ Неверный `root=` или образ диска не подключён. Проверьте `-drive file=...` и параметр `-append root=/dev/...`.

**"Address already in use"**
→ Предыдущий QEMU не завершился:
```bash
pkill -f qemu-system
```

**На RPi4/ARM-хосте очень медленно (эмуляция x86)**
→ Нормально. qemu-x86 на ARM64 эмулирует ISA полностью — загрузка занимает 20–30 с.  
Ускорить нельзя (нет KVM для другой архитектуры), но на x86-хосте с KVM будет мгновенно:
```bash
# Только на x86-хосте:
qemu-system-x86_64 -enable-kvm ...
```
