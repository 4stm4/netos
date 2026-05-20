# Сеть

## eth0

По умолчанию eth0 настроен на DHCP. Для статики задайте переменные окружения или используйте профиль:

```bash
NETOS_ETH0_ADDRESS=192.168.1.10 \
NETOS_ETH0_GATEWAY=192.168.1.1 \
NETOS_ETH0_DNS=1.1.1.1 \
python3 src/main.py --target pi5
```

В профиле:

```yaml
network:
  eth0:
    mode: static
    address: 192.168.1.10
    gateway: 192.168.1.1
    dns: 1.1.1.1
```

Если `mode: dhcp` или `address` пустой — используется DHCP.

## Wi-Fi (только zero2w)

### При сборке

```bash
NETOS_WIFI_SSID='my-wifi' \
NETOS_WIFI_PSK='password' \
NETOS_WIFI_COUNTRY=RU \
python3 src/main.py --target zero2w
```

В профиле:

```yaml
network:
  wifi:
    country: RU
    ssid: my-wifi
    psk: password
    bootstrap: true
```

### После записи SD-карты

Положите `wpa_supplicant.conf` или `netos-wifi.conf` на FAT boot-раздел. При первом boot `/etc/init.d/S39wifi` подберёт файл, скопирует в `/etc/wpa_supplicant.conf` и поднимет `wlan0`:

```conf
ctrl_interface=/var/run/wpa_supplicant
update_config=1
country=RU

network={
    ssid="my-wifi"
    psk="password"
}
```

`NETOS_WIFI_BOOTSTRAP=0` отключает эту логику.

## Open vSwitch / OVSDB

Open vSwitch собирается как external Buildroot package и запускается при старте через `/etc/init.d/S99netos`:

- `ovsdb-server` слушает на `/var/run/openvswitch/db.sock` и TCP `6640`
- `ovs-vswitchd` управляет datapath

### Подключение к OVSDB

Локально на устройстве:

```bash
ovs-vsctl show
ovsdb-client dump
```

Удалённо (QEMU с port forward 6641→6640):

```bash
ovsdb-client -p 6641 dump
ovs-vsctl --db=tcp:127.0.0.1:6641 show
```

### OVSDB Schema

Схема находится в `src/schema/system.ovsschema`. Копируется в rootfs при сборке и используется `ovsdb-server` как основная база конфигурации узла.

### Агенты управления

Агенты запускаются вместе с OVSDB и подписываются на изменения в базе:

| Агент | Файл | Назначение |
|---|---|---|
| `net_agent` | `src/agents/net_agent.py` | Сетевые интерфейсы, bridge, hostname, timezone |
| `storage_agent` | `src/agents/storage_agent.py` | iSCSI login/mount |
| `vm_agent` | `src/agents/vm_agent.py` | Управление VM-процессами, cgroup |
| `stat_agent` | `src/agents/stat_agent.py` | Телеметрия узла |

### SDN-контроллер Nervum

Nervum — это не пакет Buildroot. Он устанавливается через pip в `/opt/testum/.python` при сборке образа.

Настройка через env:

```bash
NETOS_NERVUM_GIT_URL=https://github.com/4stm4/nervum.git \
NETOS_NERVUM_GIT_REF=main \
python3 src/main.py --target qemu-virt
```

Или через локальные исходники:

```bash
NETOS_NERVUM_SOURCE_DIR=/path/to/nervum \
python3 src/main.py --target qemu-virt
```

В web-конфигураторе Nervum настраивается на шаге 4 (Web UI & Nervum), а не в разделе пакетов.

## Firewall

netOS использует `nftables`. Базовые правила задаются в rootfs overlay. Для кастомных правил добавьте файл в `/etc/nftables.d/` через rootfs overlay при сборке.
