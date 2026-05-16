from pathlib import Path
import shutil
import subprocess
import logging
from core.interfaces import FileSystemPort

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FileAdapter(FileSystemPort):
    """Адаптер для работы с файловой системой."""
    rootfs_path: Path

    def __init__(self, rootfs_path: str):
        """Инициализирует адаптер с заданным путем к rootfs.

        Args:
            rootfs_path: Путь к rootfs.
        """
        self.rootfs_path = Path(rootfs_path)

    def create_directory(self, path: Path, mode: int = 0o755):
        """Создает директорию с заданными правами доступа.

        Args:
            path: Путь к директории относительно rootfs.
            mode: Права доступа (по умолчанию 0o755).
        """
        full_path = self.rootfs_path / path
        try:
            full_path.mkdir(parents=True, exist_ok=True, mode=mode)
        except OSError as e:
            logger.error(f"Error setting permissions on {full_path}: {e}")

    def copy_file(self, src: Path, dest: Path):
        """Копирует файл.

        Args:
            src: Путь к исходному файлу.
            dest: Путь к файлу назначения относительно rootfs.
        """
        full_dest = self.rootfs_path / dest
        shutil.copy2(src, full_dest)

    def write_text(self, path: Path, content: str):
        """Записывает текст в файл.

        Args:
            path: Путь к файлу относительно rootfs.
            content: Текст для записи.
        """
        full_path = self.rootfs_path / path
        full_path.write_text(content)

    def _unmount_proc(self):
        """Размонтирует proc, если он смонтирован."""
        logger.info("Размонтируем proc.")
        proc_path = self.rootfs_path / 'proc'
        if proc_path.exists() and proc_path.is_mount():
            try:
                subprocess.run(['sudo', 'umount', str(proc_path)], check=True)
                logger.info(f"Successfully unmounted {proc_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Error unmounting {proc_path}: {e}")
            except FileNotFoundError:
                logger.warning(f"sudo or umount not found. Unable to unmount {proc_path}.")

    def _clear_container_directory(self, clear_path: Path):
        """Рекурсивно удаляет содержимое директории.

        Args:
            path: Путь к директории.
        """
        if clear_path.exists():
            for item in clear_path.iterdir():
                # Не спускаемся в симлинки как в каталоги — удаляем их как файлы,
                # чтобы избежать ошибок вида "Not a directory".
                if item.is_dir() and not item.is_symlink():
                    self._clear_container_directory(item)
                else:
                    item.unlink()
            clear_path.rmdir()
            logger.debug(f"Removed directory: {clear_path}")

    def clear_container(self):
        """Очищает контейнер, размонтируя proc и удаляя содержимое rootfs."""
        self._unmount_proc()
        self._clear_container_directory(self.rootfs_path)
