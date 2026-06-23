import logging
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Iterable, Optional, Union

from netos_build.artifacts import ArtifactManager


RPI_REPO_URL = "https://github.com/raspberrypi/linux.git"
DEFAULT_RPI_BRANCH = "rpi-6.12.y"
MAINLINE_KERNEL_BASE_URL = "https://cdn.kernel.org/pub/linux/kernel"

AMNEZIAWG_VERSION = os.environ.get("NETOS_AMNEZIAWG_VERSION", "v1.0.20260611")
AMNEZIAWG_SHA256 = os.environ.get(
    "NETOS_AMNEZIAWG_SHA256",
    "e062ecc9f1d89eeafa9f56a29473372a1d796ee061eaa8c7b61eeb51c38b80d6",
)


def _env(name: str, default: Optional[str] = None, legacy_name: Optional[str] = None) -> Optional[str]:
    if name in os.environ:
        return os.environ[name]
    if legacy_name and legacy_name in os.environ:
        return os.environ[legacy_name]
    return default


RPI_FIRMWARE_BASE_URL = _env(
    "NETOS_RPI_FIRMWARE_BASE_URL",
    "https://raw.githubusercontent.com/raspberrypi/firmware/master/boot",
    legacy_name="LITAINER_RPI_FIRMWARE_BASE_URL",
)

MAINLINE_KERNEL_VERSION      = _env("NETOS_MAINLINE_KERNEL_VERSION", "6.12.27")
MAINLINE_KERNEL_SHA256       = _env("NETOS_MAINLINE_KERNEL_SHA256")  # optional; verified if set


class LinuxKernel:
    rpi_model: str
    temp_path: Path
    rpi_repo_path: Path
    kernel_image: Path
    kernel_filename: str
    rootfs_path: Path

    _KERNEL_IMAGE_REL: dict[str, str] = {
        "arm64": "arch/arm64/boot/Image",
        "x86":   "arch/x86/boot/bzImage",
    }
    _MAKE_IMAGE_TARGET: dict[str, str] = {
        "arm64": "Image",
        "x86":   "bzImage",
    }

    def __init__(
        self,
        temp_path: str,
        rpi_model: str,
        rootfs_path: Union[Path, str],
        kernel_filename: str = "kernel8.img",
        config_options: Iterable[str] = (),
        boot_firmware_files: Iterable[str] = (),
        build_modules: bool = True,
        kernel_source: str = "rpi",
        kernel_arch: str = "arm64",
        cross_compile: str = "aarch64-linux-gnu-",
        build_amneziawg: bool = False,
    ):
        self.temp_path = Path(temp_path)
        self.rpi_model = rpi_model
        # NETOS_KERNEL_SOURCE=mainline allows mainline kernel on any target (e.g. RPi)
        self.kernel_source = _env("NETOS_KERNEL_SOURCE", kernel_source) or kernel_source
        self.kernel_arch = kernel_arch
        self.cross_compile = cross_compile
        subdir = "mainline_linux" if kernel_source == "mainline" else "rpi_linux"
        self.rpi_repo_path = self.temp_path / subdir
        img_rel = self._KERNEL_IMAGE_REL.get(kernel_arch, f"arch/{kernel_arch}/boot/Image")
        self.kernel_image = self.rpi_repo_path / img_rel
        self.kernel_filename = kernel_filename
        self.rootfs_path = Path(rootfs_path)
        self.config_options = tuple(config_options)
        self.boot_firmware_files = tuple(boot_firmware_files)
        self.build_modules = build_modules
        self.build_amneziawg = build_amneziawg
        prebuilt_kernel = _env("NETOS_PREBUILT_KERNEL_IMAGE", legacy_name="LITAINER_PREBUILT_KERNEL_IMAGE")
        self.prebuilt_kernel_image = Path(prebuilt_kernel) if prebuilt_kernel else None

    @staticmethod
    def _format_config_option(option: str) -> str:
        option = option.strip()
        key, sep, value = option.partition("=")
        if sep and value == "n" and key.startswith("CONFIG_"):
            return f"# {key} is not set"
        return option

    def _kernel_modules_enabled(self) -> bool:
        config_path = self.rpi_repo_path / ".config"
        if not config_path.exists():
            return True
        for line in config_path.read_text().splitlines():
            if line == "CONFIG_MODULES=y":
                return True
            if line == "# CONFIG_MODULES is not set":
                return False
        return True

    def _download_mainline_kernel(self):
        """Скачивает и распаковывает mainline-ядро с kernel.org."""
        version = MAINLINE_KERNEL_VERSION
        major   = version.split(".")[0]
        filename = f"linux-{version}.tar.xz"
        url      = f"{MAINLINE_KERNEL_BASE_URL}/v{major}.x/{filename}"
        extract_tmp = self.temp_path / "mainline_linux.extract"

        if self.rpi_repo_path.exists() and (self.rpi_repo_path / "Makefile").exists():
            release_file = self.rpi_repo_path / "include/config/kernel.release"
            current = release_file.read_text().strip() if release_file.exists() else ""
            if version in current:
                logging.info("Mainline kernel %s уже распакован: %s", version, self.rpi_repo_path)
                return
            logging.info("Версия mainline изменилась (%s → %s), перескачиваем...", current, version)
            shutil.rmtree(self.rpi_repo_path)

        if extract_tmp.exists():
            shutil.rmtree(extract_tmp)
        extract_tmp.mkdir(parents=True)

        archive = ArtifactManager(self.temp_path).fetch(
            url=url,
            sha256=MAINLINE_KERNEL_SHA256,
            filename=filename,
        )

        logging.info("Распаковываем %s...", archive)
        subprocess.run(
            ["tar", "-xf", str(archive), "-C", str(extract_tmp), "--strip-components=1"],
            check=True,
        )
        extract_tmp.rename(self.rpi_repo_path)
        logging.info("Mainline kernel %s готов: %s", version, self.rpi_repo_path)

    def download_kernel(self):
        """Загружает или обновляет исходники ядра."""
        if self.prebuilt_kernel_image:
            if not self.prebuilt_kernel_image.exists():
                raise FileNotFoundError(f"Prebuilt kernel Image не найден: {self.prebuilt_kernel_image}")
            logging.info(f"Используем prebuilt kernel Image: {self.prebuilt_kernel_image}")
            return

        self.temp_path.mkdir(parents=True, exist_ok=True)

        if self.kernel_source == "mainline":
            self._download_mainline_kernel()
            return

        logging.info("Готовим исходники ядра Raspberry Pi...")


        git_dir = self.rpi_repo_path / ".git"
        if self.rpi_repo_path.exists() and not git_dir.exists():
            if (self.rpi_repo_path / "Makefile").exists():
                logging.info(f"Исходники ядра уже доступны в {self.rpi_repo_path}")
                return
            logging.warning(f"Удаляем неполный каталог исходников: {self.rpi_repo_path}")
            shutil.rmtree(self.rpi_repo_path)

        if not git_dir.exists():
            branch = _env("NETOS_KERNEL_BRANCH", DEFAULT_RPI_BRANCH, legacy_name="LITAINER_KERNEL_BRANCH")
            tarball_url = _env(
                "NETOS_KERNEL_TARBALL_URL",
                f"https://github.com/raspberrypi/linux/archive/refs/heads/{branch}.tar.gz",
                legacy_name="LITAINER_KERNEL_TARBALL_URL",
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
            subprocess.run(
                [
                    "make",
                    f"ARCH={self.kernel_arch}",
                    f"CROSS_COMPILE={self.cross_compile}",
                    "defconfig",
                ],
                check=True,
                cwd=self.rpi_repo_path,
            )
            return

        rpi_config_path = self.rpi_repo_path / "arch" / "arm64" / "configs" / self.rpi_model
        if not rpi_config_path.exists():
            logging.info(f"Конфигурация {self.rpi_model} не найдена в arch/arm64/configs, ищем в arm/configs...")
            rpi_config_path = self.rpi_repo_path / "arch" / "arm" / "configs" / self.rpi_model
            if not rpi_config_path.exists():
                raise FileNotFoundError(f"Конфигурация {self.rpi_model} не найдена в репозитории Raspberry Pi!")

        logging.info("Используем конфигурацию для настройки ядра...")
        subprocess.run(
            [
                "make",
                f"ARCH={self.kernel_arch}",
                f"CROSS_COMPILE={self.cross_compile}",
                self.rpi_model,
            ],
            check=True,
            cwd=self.rpi_repo_path,
        )

    def configure_kernel(self):
        """Настраиваем ядро для ARM64."""
        if self.prebuilt_kernel_image:
            logging.info("Prebuilt kernel Image задан, конфигурацию ядра пропускаем.")
            return

        logging.info(
            "Настраиваем параметры ядра для ARCH=%s (source=%s)...",
            self.kernel_arch, self.kernel_source,
        )

        if self.kernel_source == "mainline":
            subprocess.run(
                [
                    "make",
                    f"ARCH={self.kernel_arch}",
                    f"CROSS_COMPILE={self.cross_compile}",
                    "defconfig",
                ],
                check=True,
                cwd=self.rpi_repo_path,
            )
        else:
            try:
                self._use_rpi_config()
            except FileNotFoundError as e:
                logging.error(f"Ошибка: {e}. Переходим к стандартной конфигурации.")
                subprocess.run(
                    [
                        "make",
                        f"ARCH={self.kernel_arch}",
                        f"CROSS_COMPILE={self.cross_compile}",
                        "defconfig",
                    ],
                    check=True,
                    cwd=self.rpi_repo_path,
                )

        # Применяем дополнительные изменения
        config_path = self.rpi_repo_path / ".config"
        with config_path.open("a") as config_file:
            config_file.write("\n")
            config_file.write("# 4stm4 netOS kernel configuration\n")
            for option in self.config_options:
                config_file.write(f"{self._format_config_option(option)}\n")
        subprocess.run(
            [
                "make",
                f"ARCH={self.kernel_arch}",
                f"CROSS_COMPILE={self.cross_compile}",
                "olddefconfig",
            ],
            check=True,
            cwd=self.rpi_repo_path,
        )


    def compile_kernel(self):
        """Компилируем ядро инкрементально для текущей конфигурации target."""
        if self.prebuilt_kernel_image:
            self.kernel_image.parent.mkdir(parents=True, exist_ok=True)
            if self.prebuilt_kernel_image.resolve() != self.kernel_image.resolve():
                shutil.copy2(self.prebuilt_kernel_image, self.kernel_image)
            logging.info(f"Prebuilt kernel Image готов: {self.kernel_image}")
            return

        logging.info("Собираем ядро для текущего target...")
        jobs = os.environ.get("NETOS_BUILD_JOBS", str(os.cpu_count() or 1))
        img_target = self._MAKE_IMAGE_TARGET.get(self.kernel_arch, "Image")
        make_targets = [img_target] + (["dtbs"] if self.kernel_arch == "arm64" else [])
        if self.build_modules and self._kernel_modules_enabled():
            make_targets.insert(1, "modules")
        elif not self.build_modules:
            logging.info("Сборка kernel modules отключена для target, собираем только Image и DTB.")
        else:
            logging.info("CONFIG_MODULES отключен, сборку kernel modules пропускаем.")
        subprocess.run(
            [
                "make",
                f"-j{jobs}",
                f"ARCH={self.kernel_arch}",
                f"CROSS_COMPILE={self.cross_compile}",
                *make_targets,
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
            shutil.copy2(self.prebuilt_kernel_image, dest_image)
            logging.info(f"Скопирован prebuilt Image в {dest_image}; modules_install пропущен.")
            self._install_boot_firmware(boot_dir)
            return
        else:
            if self.build_modules and self._kernel_modules_enabled():
                logging.info("Устанавливаем модули ядра в rootfs...")
                subprocess.run(
                    [
                        "make",
                        f"ARCH={self.kernel_arch}",
                        f"CROSS_COMPILE={self.cross_compile}",
                        f"INSTALL_MOD_PATH={self.rootfs_path}",
                        "modules_install",
                    ],
                    check=True,
                    cwd=self.rpi_repo_path,
                )
            elif not self.build_modules:
                logging.info("Сборка kernel modules отключена для target, modules_install пропускаем.")
            else:
                logging.info("CONFIG_MODULES отключен, modules_install пропускаем.")

        if self.build_amneziawg and self.build_modules and self._kernel_modules_enabled():
            self._build_amneziawg_module()

        boot_dir = self.rootfs_path / "boot"
        boot_dir.mkdir(parents=True, exist_ok=True)

        if self.kernel_image.exists():
            dest_image = boot_dir / self.kernel_filename
            shutil.copy2(self.kernel_image, dest_image)
            logging.info(f"Скопирован Image в {dest_image}")
        else:
            logging.error(f"Image не найден: {self.kernel_image}")

        dtb_src_dir = self.rpi_repo_path / "arch" / self.kernel_arch / "boot" / "dts" / "broadcom"
        if dtb_src_dir.exists():
            for dtb_file in dtb_src_dir.glob("*.dtb"):
                shutil.copy2(dtb_file, boot_dir / dtb_file.name)
            logging.info(f"Скопированы DTB-файлы в {boot_dir}")
        else:
            logging.error(f"DTB директория не найдена: {dtb_src_dir}")

        overlays_src_dir = self.rpi_repo_path / "arch" / self.kernel_arch / "boot" / "dts" / "overlays"
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

    def _build_amneziawg_module(self):
        """Build amneziawg out-of-tree kernel module against the just-built RPi kernel."""
        url = (
            "https://github.com/amnezia-vpn/amneziawg-linux-kernel-module"
            f"/archive/refs/tags/{AMNEZIAWG_VERSION}.tar.gz"
        )
        filename = f"amneziawg-{AMNEZIAWG_VERSION}.tar.gz"
        mgr = ArtifactManager(self.temp_path)
        tarball = mgr.fetch(url=url, sha256=AMNEZIAWG_SHA256, filename=filename, timeout=120)

        extract_dir = self.temp_path / "amneziawg-build"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)
        with tarfile.open(tarball) as tf:
            tf.extractall(extract_dir)

        subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
        if not subdirs:
            raise RuntimeError("amneziawg tarball extracted no directories")
        src_dir = subdirs[0]

        jobs = os.environ.get("NETOS_BUILD_JOBS", str(os.cpu_count() or 1))
        logging.info("Собираем amneziawg kernel module (KDIR=%s)...", self.rpi_repo_path)
        subprocess.run(
            [
                "make", f"-j{jobs}",
                "-C", "src",
                f"KDIR={self.rpi_repo_path}",
                f"ARCH={self.kernel_arch}",
                f"CROSS_COMPILE={self.cross_compile}",
            ],
            check=True,
            cwd=src_dir,
        )

        result = subprocess.run(
            ["make", "-s", f"ARCH={self.kernel_arch}", f"CROSS_COMPILE={self.cross_compile}", "kernelrelease"],
            check=True,
            cwd=self.rpi_repo_path,
            capture_output=True,
            text=True,
        )
        kver = result.stdout.strip()

        ko_src = src_dir / "src" / "amneziawg.ko"
        ko_dst_dir = self.rootfs_path / "lib" / "modules" / kver / "extra"
        ko_dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ko_src, ko_dst_dir / "amneziawg.ko")
        logging.info("Установлен amneziawg.ko → %s", ko_dst_dir)

    def _install_boot_firmware(self, boot_dir: Path):
        if not self.boot_firmware_files:
            return

        source_dir_raw = _env("NETOS_RPI_FIRMWARE_DIR", legacy_name="LITAINER_RPI_FIRMWARE_DIR")
        source_dir = Path(source_dir_raw).expanduser() if source_dir_raw else None
        mgr = ArtifactManager(self.temp_path)

        for rel_path in self.boot_firmware_files:
            destination = boot_dir / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source_dir:
                source = source_dir / rel_path
                if not source.exists():
                    raise FileNotFoundError(f"Raspberry Pi firmware file not found: {source}")
            else:
                # Firmware files have no known SHA-256 — cache by filename only
                url    = f"{RPI_FIRMWARE_BASE_URL.rstrip('/')}/{rel_path}"
                source = mgr.fetch(
                    url=url,
                    filename=f"rpi_firmware_{rel_path.replace('/', '_')}",
                    timeout=120,
                )
            shutil.copy2(source, destination)
            logging.info("Скопирован firmware-файл: %s -> %s", source, destination)
