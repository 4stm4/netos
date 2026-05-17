import logging
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Iterable, Union


RPI_REPO_URL = "https://github.com/raspberrypi/linux.git"
DEFAULT_RPI_BRANCH = "rpi-6.6.y"
RPI_FIRMWARE_BASE_URL = os.environ.get(
    "LITAINER_RPI_FIRMWARE_BASE_URL",
    "https://raw.githubusercontent.com/raspberrypi/firmware/master/boot",
)

DEFAULT_KERNEL_CONFIG_OPTIONS = (
    "CONFIG_CGROUPS=y",
    "CONFIG_NAMESPACES=y",
    "CONFIG_OVERLAY_FS=y",
    "CONFIG_TMPFS=y",
    "CONFIG_IPV6=y",
    "CONFIG_KVM=y",
    "CONFIG_VHOST_NET=y",
    "CONFIG_VFIO=y",
    "CONFIG_VFIO_PCI=y",
    "CONFIG_ISCSI_TCP=y",
    "CONFIG_MULTIPATH=y",
    "CONFIG_WATCHDOG=y",
)

class LinuxKernel:
    rpi_model: str
    temp_path: Path
    rpi_repo_path: Path
    kernel_image: Path
    kernel_filename: str
    rootfs_path: Path

    def __init__(
        self,
        temp_path: str,
        rpi_model: str,
        rootfs_path: Union[Path, str],
        kernel_filename: str = "kernel8.img",
        config_options: Iterable[str] = DEFAULT_KERNEL_CONFIG_OPTIONS,
        boot_firmware_files: Iterable[str] = (),
    ):
        self.temp_path = Path(temp_path)
        self.rpi_model = rpi_model
        self.rpi_repo_path = self.temp_path / "rpi_linux"
        self.kernel_image = self.rpi_repo_path / "arch/arm64/boot/Image"
        self.kernel_filename = kernel_filename
        self.rootfs_path = Path(rootfs_path)
        self.config_options = tuple(config_options)
        self.boot_firmware_files = tuple(boot_firmware_files)
        prebuilt_kernel = os.environ.get("LITAINER_PREBUILT_KERNEL_IMAGE")
        self.prebuilt_kernel_image = Path(prebuilt_kernel) if prebuilt_kernel else None

    def download_kernel(self):
        """Загружает или обновляет исходники ядра Raspberry Pi."""
        if self.prebuilt_kernel_image:
            if not self.prebuilt_kernel_image.exists():
                raise FileNotFoundError(f"Prebuilt kernel Image не найден: {self.prebuilt_kernel_image}")
            logging.info(f"Используем prebuilt kernel Image: {self.prebuilt_kernel_image}")
            return

        logging.info("Готовим исходники ядра Raspberry Pi...")
        self.temp_path.mkdir(parents=True, exist_ok=True)

        git_dir = self.rpi_repo_path / ".git"
        if self.rpi_repo_path.exists() and not git_dir.exists():
            if (self.rpi_repo_path / "Makefile").exists():
                logging.info(f"Исходники ядра уже доступны в {self.rpi_repo_path}")
                return
            logging.warning(f"Удаляем неполный каталог исходников: {self.rpi_repo_path}")
            shutil.rmtree(self.rpi_repo_path)

        if not git_dir.exists():
            branch = os.environ.get("LITAINER_KERNEL_BRANCH", DEFAULT_RPI_BRANCH)
            tarball_url = os.environ.get(
                "LITAINER_KERNEL_TARBALL_URL",
                f"https://github.com/raspberrypi/linux/archive/refs/heads/{branch}.tar.gz",
            )
            if self._download_kernel_tarball(tarball_url, branch):
                return

            logging.info(f"Клонируем {RPI_REPO_URL} ({branch}) в {self.rpi_repo_path}")
            clone_tmp = self.temp_path / "rpi_linux.clone"
            if clone_tmp.exists():
                shutil.rmtree(clone_tmp)
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth=1",
                    "--single-branch",
                    "--branch",
                    branch,
                    "--filter=blob:none",
                    RPI_REPO_URL,
                    str(clone_tmp),
                ],
                check=True,
                cwd=self.temp_path,
            )
            clone_tmp.rename(self.rpi_repo_path)
            return

        logging.info("Репозиторий уже клонирован, обновляем...")
        subprocess.run(["git", "rev-parse", "--verify", "HEAD"], check=True, cwd=self.rpi_repo_path)
        subprocess.run(["git", "pull", "--ff-only"], check=True, cwd=self.rpi_repo_path)

    def _download_kernel_tarball(self, tarball_url: str, branch: str) -> bool:
        archive_path = self.temp_path / f"rpi_linux-{branch}.tar.gz"
        extract_tmp = self.temp_path / "rpi_linux.extract"

        if extract_tmp.exists():
            shutil.rmtree(extract_tmp)
        if archive_path.exists():
            archive_path.unlink()
        extract_tmp.mkdir(parents=True)

        logging.info(f"Скачиваем архив ядра: {tarball_url}")
        try:
            subprocess.run(
                ["wget", "-O", str(archive_path), "--tries=3", "--timeout=30", tarball_url],
                check=True,
                cwd=self.temp_path,
            )
            subprocess.run(
                [
                    "tar",
                    "-xzf",
                    str(archive_path),
                    "-C",
                    str(extract_tmp),
                    "--strip-components=1",
                ],
                check=True,
            )
            extract_tmp.rename(self.rpi_repo_path)
            return True
        except subprocess.CalledProcessError as exc:
            logging.warning(f"Не удалось скачать/распаковать архив ядра: {exc}")
            if extract_tmp.exists():
                shutil.rmtree(extract_tmp)
            if archive_path.exists():
                archive_path.unlink()
            return False

    def unpack_kernel(self):
        """Совместимость с прежним API: исходники уже подготовлены."""
        logging.info(f"Исходники доступны в {self.rpi_repo_path}")

    def _use_rpi_config(self):
        """
        Готовит конфигурацию ядра для указанной модели Raspberry Pi.
        """
        if not (self.rpi_repo_path / "Makefile").exists():
            raise FileNotFoundError(f"Исходники ядра не найдены: {self.rpi_repo_path}")

        if self.rpi_model == "defconfig":
            logging.info("Используем стандартный ARM64 defconfig.")
            subprocess.run(["make", "ARCH=arm64", "defconfig"], check=True, cwd=self.rpi_repo_path)
            return

        rpi_config_path = self.rpi_repo_path / "arch" / "arm64" / "configs" / self.rpi_model
        if not rpi_config_path.exists():
            logging.info(f"Конфигурация {self.rpi_model} не найдена в arch/arm64/configs, ищем в arm/configs...")
            rpi_config_path = self.rpi_repo_path / "arch" / "arm" / "configs" / self.rpi_model
            if not rpi_config_path.exists():
                raise FileNotFoundError(f"Конфигурация {self.rpi_model} не найдена в репозитории Raspberry Pi!")

        logging.info("Используем конфигурацию для настройки ядра...")
        subprocess.run(["make", "ARCH=arm64", self.rpi_model], check=True, cwd=self.rpi_repo_path)

    def configure_kernel(self):
        """
        Настраиваем ядро для ARM64 с использованием либо стандартной конфигурации,
        либо конфигурации Raspberry Pi.
        """
        if self.prebuilt_kernel_image:
            logging.info("Prebuilt kernel Image задан, конфигурацию ядра пропускаем.")
            return

        logging.info("Настраиваем параметры ядра для ARM64...")

        try:
            self._use_rpi_config()
        except FileNotFoundError as e:
            logging.error(f"Ошибка: {e}. Переходим к стандартной конфигурации.")
            subprocess.run(["make", "ARCH=arm64", "defconfig"], check=True, cwd=self.rpi_repo_path)

        # Применяем дополнительные изменения
        config_path = self.rpi_repo_path / ".config"
        with config_path.open("a") as config_file:
            config_file.write("\n")
            config_file.write("# Litainer kernel configuration\n")
            for option in self.config_options:
                config_file.write(f"{option}\n")
        subprocess.run(["make", "ARCH=arm64", "olddefconfig"], check=True, cwd=self.rpi_repo_path)


    def compile_kernel(self):
        """Компилируем ядро инкрементально для текущей конфигурации target."""
        if self.prebuilt_kernel_image:
            self.kernel_image.parent.mkdir(parents=True, exist_ok=True)
            if self.prebuilt_kernel_image.resolve() != self.kernel_image.resolve():
                shutil.copy2(self.prebuilt_kernel_image, self.kernel_image)
            logging.info(f"Prebuilt kernel Image готов: {self.kernel_image}")
            return

        logging.info("Собираем ядро для текущего target...")
        nproc = os.cpu_count() or 1
        subprocess.run(
            [
                "make",
                f"-j{nproc}",
                "ARCH=arm64",
                "CROSS_COMPILE=aarch64-linux-gnu-",
                "Image",
                "modules",
                "dtbs",
            ],
            check=True,
            cwd=self.rpi_repo_path,
        )

    def install_kernel(self):
        """Устанавливаем модули в rootfs и копируем Image/DTB в /boot."""
        if self.prebuilt_kernel_image:
            boot_dir = self.rootfs_path / "boot"
            boot_dir.mkdir(parents=True, exist_ok=True)
            dest_image = boot_dir / self.kernel_filename
            shutil.copy2(self.kernel_image, dest_image)
            logging.info(f"Скопирован prebuilt Image в {dest_image}; modules_install пропущен.")
        else:
            logging.info("Устанавливаем модули ядра в rootfs...")
            subprocess.run(
                [
                    "make",
                    "ARCH=arm64",
                    "CROSS_COMPILE=aarch64-linux-gnu-",
                    f"INSTALL_MOD_PATH={self.rootfs_path}",
                    "modules_install",
                ],
                check=True,
                cwd=self.rpi_repo_path,
            )

        boot_dir = self.rootfs_path / "boot"
        boot_dir.mkdir(parents=True, exist_ok=True)

        if self.kernel_image.exists():
            dest_image = boot_dir / self.kernel_filename
            shutil.copy2(self.kernel_image, dest_image)
            logging.info(f"Скопирован Image в {dest_image}")
        else:
            logging.error(f"Image не найден: {self.kernel_image}")

        dtb_src_dir = self.rpi_repo_path / "arch" / "arm64" / "boot" / "dts" / "broadcom"
        if dtb_src_dir.exists():
            for dtb_file in dtb_src_dir.glob("*.dtb"):
                shutil.copy2(dtb_file, boot_dir / dtb_file.name)
            logging.info(f"Скопированы DTB-файлы в {boot_dir}")
        else:
            logging.error(f"DTB директория не найдена: {dtb_src_dir}")

        overlays_src_dir = self.rpi_repo_path / "arch" / "arm64" / "boot" / "dts" / "overlays"
        if overlays_src_dir.exists():
            dest_overlays_dir = boot_dir / "overlays"
            if dest_overlays_dir.exists():
                shutil.rmtree(dest_overlays_dir)
            dest_overlays_dir.mkdir(parents=True)
            copied = 0
            for pattern in ("*.dtbo", "*.dtbo.disabled", "overlay_map.dtb", "README*"):
                for overlay_file in overlays_src_dir.glob(pattern):
                    if overlay_file.is_file():
                        shutil.copy2(overlay_file, dest_overlays_dir / overlay_file.name)
                        copied += 1
            if copied == 0:
                logging.error(f"Готовые overlay-файлы не найдены в {overlays_src_dir}")
            logging.info(f"Скопированы overlays в {dest_overlays_dir}")
        else:
            logging.error(f"Директория overlays не найдена: {overlays_src_dir}")

        self._install_boot_firmware(boot_dir)

    def _install_boot_firmware(self, boot_dir: Path):
        if not self.boot_firmware_files:
            return

        source_dir_raw = os.environ.get("LITAINER_RPI_FIRMWARE_DIR")
        source_dir = Path(source_dir_raw).expanduser() if source_dir_raw else None
        cache_dir = self.temp_path / "rpi_firmware_boot"
        cache_dir.mkdir(parents=True, exist_ok=True)

        for rel_path in self.boot_firmware_files:
            destination = boot_dir / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source_dir:
                source = source_dir / rel_path
                if not source.exists():
                    raise FileNotFoundError(f"Raspberry Pi firmware file not found: {source}")
            else:
                source = cache_dir / rel_path
                if not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    url = f"{RPI_FIRMWARE_BASE_URL.rstrip('/')}/{rel_path}"
                    logging.info("Downloading Raspberry Pi firmware: %s", url)
                    urllib.request.urlretrieve(url, source)
            shutil.copy2(source, destination)
            logging.info("Скопирован firmware-файл: %s -> %s", source, destination)
