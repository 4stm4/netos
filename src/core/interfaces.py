from abc import ABC, abstractmethod
from pathlib import Path

class FileSystemPort(ABC):
    @abstractmethod
    def create_directory(self, path: Path, mode: int = 0o755):
        pass

    @abstractmethod
    def copy_file(self, src: Path, dest: Path):
        pass

    @abstractmethod
    def write_text(self, path: Path, content: str):
        pass

class LoggerPort(ABC):
    @abstractmethod
    def info(self, message: str, *args):
        pass

    @abstractmethod
    def error(self, message: str, *args):
        pass

class NetworkConfiguratorPort(ABC):
    @abstractmethod
    def setup_network(self, rootfs_path: Path):
        pass
