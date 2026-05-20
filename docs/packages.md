# Пакеты

## Как работает пакетная система Buildroot

В netOS нет `apt`, `dpkg` или `rpm`. Все пакеты **компилируются из исходников на этапе сборки образа** и включаются в rootfs статически.

Buildroot управляет пакетами через конфигурационные переменные в `_defconfig`:

```
BR2_PACKAGE_TCPDUMP=y
BR2_PACKAGE_HTOP=y
```

Каждая такая строка означает: «включить пакет в образ». Пакеты, не указанные в defconfig, в образ не попадают. Добавить пакет после сборки без пересборки образа нельзя.

External-пакеты (те, которых нет в основном Buildroot) находятся в `netos-buildroot-external/package/`.

---

## Категории пакетов

В `packages.yaml` описаны **110 пакетов** в **9 категориях**:

| Категория | Описание | Примеры пакетов |
|-----------|----------|-----------------|
| `core` | Базовые системные утилиты | `busybox`, `util-linux`, `e2fsprogs` |
| `networking` | Сетевые инструменты | `tcpdump`, `iperf3`, `nmap`, `curl`, `wget` |
| `monitoring` | Мониторинг ресурсов | `htop`, `iotop`, `sysstat`, `lm-sensors` |
| `security` | Безопасность | `fail2ban`, `iptables`, `nftables`, `openssl` |
| `storage` | Управление хранилищами | `lvm2`, `mdadm`, `parted`, `e2fsprogs` |
| `ovs_kvm` | Open vSwitch и виртуализация | `openvswitch`, `qemu`, `libvirt` |
| `dev_debug` | Разработка и отладка | `strace`, `gdb`, `ltrace`, `valgrind` |
| `python` | Python и библиотеки | `python3`, `python3-pip`, `python3-requests` |
| `webui` | Зависимости Web UI | `nginx`, `sqlite`, зависимости Testum |

---

## Пресеты

### Minimal

6 пакетов — минимальная рабочая система с SSH и базовыми утилитами:

- `busybox`
- `dropbear` (SSH)
- `e2fsprogs`
- `util-linux`
- `openssl`
- `ca-certificates`

### Full netOS

Все ~70 пакетов по умолчанию — полноценная сетевая ОС с OVS, мониторингом и веб-интерфейсом. Включает все категории кроме `dev_debug` и тяжёлых отладочных инструментов.

---

## Способы добавить пакеты

### 1. Через профиль YAML (рекомендуется)

Поле `packages.enabled` — список ключей пакетов из `packages.yaml`:

```yaml
packages:
  enabled:
    - tcpdump
    - htop
    - iperf3
    - strace
```

### 2. Кастомные BR2_PACKAGE строки в профиле

Поле `packages.custom` — произвольные строки `BR2_PACKAGE_*=y`:

```yaml
packages:
  custom:
    - BR2_PACKAGE_NANO=y
    - BR2_PACKAGE_VIM=y
    - BR2_PACKAGE_PYTHON3_PARAMIKO=y
```

Используется для пакетов, которых нет в `packages.yaml`, но которые есть в Buildroot.

### 3. Через файл `--packages-file`

Текстовый файл с одной строкой на пакет:

```
BR2_PACKAGE_TCPDUMP=y
BR2_PACKAGE_HTOP=y
```

```bash
python3 src/main.py --target qemu-virt --packages-file extra.txt
```

### 4. Напрямую в `netos_buildroot.py`

Для постоянных изменений, которые должны быть в всех сборках, можно добавить строки напрямую в функцию `_defconfig()` в `src/netos_buildroot.py`. Это изменение кода — делается только если пакет является частью базовой конфигурации проекта.

---

## Nervum / SDN-контроллер

### Что такое Nervum

Nervum — SDN-контроллер из репозитория `https://github.com/4stm4/nervum`. Он управляет Open vSwitch через OVSDB и обеспечивает сетевую логику netOS.

### Почему это не BR2_PACKAGE

Nervum **не является пакетом Buildroot**. Он устанавливается через `pip` в изолированное виртуальное окружение:

```
/opt/testum/.python/
```

Это происходит на этапе overlay при сборке образа, после завершения Buildroot-сборки.

### Настройка

Через переменные окружения:

```bash
export NETOS_NERVUM_GIT_URL=https://github.com/4stm4/nervum
export NETOS_NERVUM_GIT_REF=main
```

Через профиль YAML (поле `webui`, т.к. Nervum устанавливается вместе с Testum):

```yaml
webui:
  git_url: https://github.com/4stm4/testum.git
  git_ref: main
```

Для offline-сборки (без доступа к GitHub) используйте `NETOS_NERVUM_SOURCE_DIR` с путём к локальной копии.

### Дополнительные pip-зависимости

Для установки дополнительных Python-пакетов в то же окружение используйте `NETOS_NERVUM_VENDOR_PACKAGES` — список пакетов через пробел.

---

## Open vSwitch

Open vSwitch (OVS) собирается как **external Buildroot package** из директории:

```
netos-buildroot-external/package/openvswitch/
```

Версия задаётся переменной `NETOS_OPENVSWITCH_VERSION` (по умолчанию `3.4.1`).

OVS включается в образ через категорию `ovs_kvm` в `packages.yaml`. При включении в defconfig добавляются:

```
BR2_PACKAGE_OPENVSWITCH=y
```

OVSDB-сервер и `ovs-vswitchd` стартуют через init-скрипты при загрузке.
