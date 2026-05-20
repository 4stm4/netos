# Справочник переменных окружения

Все переменные имеют префикс `NETOS_`. Для обратной совместимости работают также алиасы `LITAINER_*` — они являются синонимами соответствующих `NETOS_*` переменных.

---

## Управление сборкой

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `NETOS_BUILD_JOBS` | число CPU | Количество параллельных потоков `make`. По умолчанию `nproc`. |
| `NETOS_BUILDROOT_VERSION` | (задано в коде) | Версия Buildroot для загрузки, например `2024.02`. |
| `NETOS_BUILDROOT_SHA256` | (задано в коде) | SHA256-хеш tarball'а Buildroot для верификации. |

---

## Ядро

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `NETOS_KERNEL_BRANCH` | `rpi-6.12.y` | Ветка ядра для RPi-целей (из `raspberrypi/linux`). |
| `NETOS_MAINLINE_KERNEL_VERSION` | `6.12.27` | Версия mainline-ядра для QEMU-целей (с `kernel.org`). |
| `NETOS_KERNEL_TARBALL_URL` | (вычисляется) | Явный URL tarball'а ядра. Переопределяет автоматический URL по версии. |
| `NETOS_PREBUILT_KERNEL_IMAGE` | не задано | Путь к готовому образу ядра. Если задан — пропускает сборку ядра. |

---

## Open vSwitch

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `NETOS_OPENVSWITCH_VERSION` | `3.4.1` | Версия Open vSwitch для сборки. |
| `NETOS_OPENVSWITCH_SHA256` | (задано в коде) | SHA256-хеш исходников OVS для верификации. |

---

## Образ

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `NETOS_IMAGE_SIZE_MB` | `512` | Полный размер итогового образа в МБ. |
| `NETOS_BOOT_SIZE_MB` | `64` | Размер FAT boot-раздела в МБ (только для RPi-целей). |

---

## Брендинг

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `NETOS_VERSION` | `0.1.0` | Версия образа; попадает в `/etc/netos-release`. |
| `NETOS_HOSTNAME` | `4stm4-netos` | hostname системы в образе. |

---

## Сеть

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `NETOS_ETH0_ADDRESS` | не задано | IP-адрес eth0 в формате `192.168.1.10/24` (только для static). |
| `NETOS_ETH0_GATEWAY` | не задано | Шлюз по умолчанию (только для static). |
| `NETOS_ETH0_DNS` | не задано | DNS-сервер (только для static). |
| `NETOS_WIFI_SSID` | не задано | SSID Wi-Fi сети (только `zero2w`). |
| `NETOS_WIFI_PSK` | не задано | Пароль Wi-Fi. |
| `NETOS_WIFI_COUNTRY` | `US` | Код страны Wi-Fi (ISO 3166-1 alpha-2), например `RU`. |
| `NETOS_WIFI_BOOTSTRAP` | `true` | Поднять Wi-Fi при первом старте системы. |

---

## Прошивка Raspberry Pi

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `NETOS_RPI_FIRMWARE_DIR` | не задано | Путь к локальной директории с RPi firmware (boot-файлы). Если не задан — firmware скачивается автоматически. |
| `NETOS_RPI_FIRMWARE_BASE_URL` | (задано в коде) | Базовый URL для скачивания RPi firmware. |

---

## Web UI (Testum)

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `NETOS_WEBUI_PORT` | `8080` | Порт, на котором Web UI слушает внутри образа. |
| `NETOS_WEBUI_GIT_URL` | `https://github.com/4stm4/testum.git` | URL git-репозитория Web UI. |
| `NETOS_WEBUI_GIT_REF` | `main` | Ветка или тег для клонирования. |
| `NETOS_WEBUI_SOURCE_DIR` | не задано | Путь к локальным исходникам Web UI (используется вместо git). |
| `NETOS_WEBUI_EMBED` | `true` | Встроить Web UI в образ при сборке. |
| `NETOS_WEBUI_DATA_DIR` | `/opt/testum/data` | Директория для данных Web UI (БД, файлы конфигурации). |
| `NETOS_WEBUI_DATABASE_URL` | `sqlite:///...` | URL базы данных (по умолчанию SQLite). |
| `NETOS_WEBUI_PIP_MODE` | `online` | `online` — pip скачивает зависимости; `offline` — из кеша. |
| `NETOS_WEBUI_ADMIN_USERNAME` | `admin` | Имя пользователя администратора Web UI. |
| `NETOS_WEBUI_ADMIN_PASSWORD` | не задано | Пароль администратора Web UI (обязателен для prod). |
| `NETOS_WEBUI_APP_MODULE` | (задано в коде) | ASGI-модуль приложения для uvicorn, например `testum.main:app`. |
| `NETOS_WEBUI_HEALTH_PATH` | `/health` | HTTP-путь для проверки готовности Web UI. |

---

## Nervum (SDN-контроллер)

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `NETOS_NERVUM_GIT_URL` | `https://github.com/4stm4/nervum` | URL репозитория Nervum. |
| `NETOS_NERVUM_GIT_REF` | `main` | Ветка или тег Nervum. |
| `NETOS_NERVUM_SOURCE_DIR` | не задано | Локальный путь к исходникам Nervum (для offline-сборки). |
| `NETOS_NERVUM_VENDOR_PACKAGES` | не задано | Дополнительные pip-пакеты для установки в окружение Nervum (через пробел). |

---

## Обратная совместимость

Переменные `LITAINER_*` являются алиасами `NETOS_*` и принимаются во всех местах, где принимаются `NETOS_*`. Их использование устарело — рекомендуется переходить на `NETOS_*` префикс.

Примеры алиасов:

| Старое имя | Новое имя |
|------------|-----------|
| `LITAINER_BUILD_JOBS` | `NETOS_BUILD_JOBS` |
| `LITAINER_WEBUI_PORT` | `NETOS_WEBUI_PORT` |
| `LITAINER_NERVUM_GIT_URL` | `NETOS_NERVUM_GIT_URL` |
| `LITAINER_IMAGE_SIZE_MB` | `NETOS_IMAGE_SIZE_MB` |
